"""Nivel `guest` dentro del grafo (ADR 0013): nodo, skill de respaldo, gate y routing."""

from __future__ import annotations

import dataclasses
import re
from typing import Any
from unittest.mock import AsyncMock

import pytest
from apps.api.agents.graph import route_after_execute_skill, route_after_resolve_identity
from apps.api.agents.nodes import execute_skill
from apps.api.agents.nodes.execute_skill import make_execute_skill_node
from apps.api.agents.nodes.resolve_identity import make_resolve_identity_node
from apps.api.integrations.base import IntegrationContext
from apps.api.integrations.commerce import ALL_CAPABILITIES, CommerceCapability
from apps.api.services.fixed_texts import fixed_text
from apps.api.services.identity import (
    Grant,
    IdentityContext,
    IdentityEvidence,
    sender_identity,
)
from apps.api.services.skill_access import visible_skills
from apps.api.skills.base import SkillContext
from apps.api.skills.identity.check_order_contact import CheckOrderContact
from apps.api.skills.registry import SkillRegistry
from apps.api.skills.shopify.cancel_order import CancelOrder
from apps.api.skills.shopify.get_order_status import GetOrderStatus
from apps.api.skills.shopify.get_product_info import GetProductInfo
from apps.api.skills.shopify.list_my_orders import ListMyOrders
from apps.api.skills.shopify.tag_order import TagOrder
from apps.api.skills.shopify.update_shipping_address import UpdateShippingAddress
from apps.api.tests.conftest import TENANT_ID, make_fake_tenant_scope
from apps.api.tests.identity_support import SALT, identity_state
from apps.api.tests.test_identity_guest import Store, _adapter

NODE = "apps.api.agents.nodes.resolve_identity"
CHECK = "identity.check_order_contact"


@pytest.fixture(autouse=True)
def _db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(f"{NODE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{NODE}.get_tenant_pii_salt", AsyncMock(return_value=SALT))
    monkeypatch.setattr(f"{NODE}.load_guest_grants", AsyncMock(return_value=()))


@pytest.fixture(autouse=True)
def _registry() -> None:
    """Otros tests vacían el registry (`_reset`); aquí hace falta la skill de respaldo."""
    for skill in (CheckOrderContact, GetOrderStatus, CancelOrder, GetProductInfo):
        SkillRegistry.register(skill)


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Store:
    s = Store()
    s.install(monkeypatch)
    return s


def _commerce(monkeypatch: pytest.MonkeyPatch, adapter: Any | None = None) -> None:
    real = execute_skill.build_skill_context

    def _ctx(state: Any) -> SkillContext:
        return dataclasses.replace(
            real(state),
            integration_ctx=IntegrationContext(tenant_id=TENANT_ID, credentials={}, config={}),
            commerce=adapter or _adapter(),
        )

    monkeypatch.setattr(f"{NODE}.build_skill_context", _ctx)
    monkeypatch.setattr("apps.api.agents.nodes.execute_skill.build_skill_context", _ctx)


def _turn(*messages: str, channel: str = "zendesk", **extra: Any) -> dict[str, Any]:
    state = identity_state(channel=channel, **extra)
    evidence = state["conversation_history"][0]["metadata"]
    history = [
        {"id": f"m{i}", "role": "customer", "content": text, "metadata": {}}
        for i, text in enumerate(messages)
    ]
    history[-1]["metadata"] = evidence
    state.update(conversation_history=history, inbound_message_id=history[-1]["id"])
    state.pop("identity")
    state.pop("claim_salt")
    return state


def _grants(out: dict[str, Any]) -> tuple[Grant, ...]:
    return IdentityContext.from_state(out["identity"]).grants


# ─── resolve_identity ─────────────────────────────────────────────────────────


async def test_chat_with_order_number_and_matching_email_grants_guest(
    fake_deps, monkeypatch: pytest.MonkeyPatch, store: Store
) -> None:
    _commerce(monkeypatch)
    state = _turn("Mi pedido es el #1001", "mi email es Ana@Tienda.com")
    state["known_facts"] = "previo"
    out = await make_resolve_identity_node(fake_deps)(state)
    assert [(g.level, g.order_id) for g in _grants(out)] == [("guest", 9001)]
    assert out["identity_summary"] == {"level": "guest", "methods": ["order_contact"]}
    assert out["identity_missing"] == []
    assert out["known_facts"].startswith("previo")
    assert "#1001" in out["known_facts"]
    assert "agent_response" not in out
    assert "ana@tienda.com" not in str({k: v for k, v in out.items() if k != "claim_salt"})


async def test_helpdesk_chat_requester_email_counts_as_provided_data(
    fake_deps, monkeypatch: pytest.MonkeyPatch, store: Store
) -> None:
    _commerce(monkeypatch)
    state = _turn("Quiero saber del pedido 1001")
    state["conversation_history"][0]["metadata"] = {"provided_contact": {"email": "ana@tienda.com"}}
    out = await make_resolve_identity_node(fake_deps)(state)
    assert [g.level for g in _grants(out)] == ["guest"]


async def test_the_email_typed_in_a_chat_alone_is_never_a_sender(
    fake_deps, monkeypatch: pytest.MonkeyPatch, store: Store
) -> None:
    _commerce(monkeypatch)
    out = await make_resolve_identity_node(fake_deps)(_turn("soy ana@tienda.com"))
    assert _grants(out) == ()
    assert out["identity_missing"] == ["order_number"]
    assert "Falta el número de pedido" in out["identity_note"]
    assert "agent_response" not in out


async def test_store_down_while_checking_escalates_instead_of_blaming_the_customer(
    fake_deps, monkeypatch: pytest.MonkeyPatch, store: Store
) -> None:
    # EX-01: con la tienda caída, pedirle otro email al cliente no arregla nada.
    _commerce(monkeypatch, _adapter(fail=True))
    out = await make_resolve_identity_node(fake_deps)(_turn("pedido 1001 ana@tienda.com"))
    assert _grants(out) == ()
    assert out["decision"] == "escalate"
    assert out["agent_response"] == fixed_text("commerce_unavailable", "es")
    assert out["escalation_reason"].startswith("commerce_unavailable:")
    assert route_after_resolve_identity({**out, "error": None}) == "escalate"


@pytest.mark.parametrize(
    ("messages", "missing"),
    [
        (("hola",), ["order_number", "contact"]),
        (("pedido 1001",), ["contact"]),
    ],
)
async def test_missing_data_is_named_for_the_agent(
    fake_deps,
    monkeypatch: pytest.MonkeyPatch,
    store: Store,
    messages: tuple[str, ...],
    missing: list[str],
) -> None:
    _commerce(monkeypatch)
    out = await make_resolve_identity_node(fake_deps)(_turn(*messages))
    assert out["identity_missing"] == missing


async def test_a_correct_email_with_another_customers_order_ends_with_the_fixed_text(
    fake_deps, monkeypatch: pytest.MonkeyPatch, store: Store
) -> None:
    _commerce(monkeypatch)
    out = await make_resolve_identity_node(fake_deps)(_turn("pedido 1002 ana@tienda.com"))
    assert _grants(out) == ()
    assert out["decision"] == "respond"
    assert out["agent_response"] == fixed_text("guest_not_verified", "es")
    assert out["awaiting_customer_reply"] is True
    assert route_after_resolve_identity({**out, "error": None}) == "respond"


async def test_unknown_order_gets_the_very_same_reply(
    fake_deps, monkeypatch: pytest.MonkeyPatch, store: Store
) -> None:
    _commerce(monkeypatch)
    wrong = await make_resolve_identity_node(fake_deps)(_turn("pedido 1002 ana@tienda.com"))
    store.rows.clear()
    unknown = await make_resolve_identity_node(fake_deps)(_turn("pedido 7777 ana@tienda.com"))
    assert wrong["agent_response"] == unknown["agent_response"]
    assert wrong["identity_summary"] == unknown["identity_summary"]


async def test_a_verified_sender_keeps_the_turn_when_a_guess_fails(
    fake_deps, monkeypatch: pytest.MonkeyPatch, store: Store
) -> None:
    _commerce(monkeypatch)
    state = _turn("pedido 1002 ana@tienda.com", email="ana@tienda.com", channel="email")
    out = await make_resolve_identity_node(fake_deps)(state)
    assert out["identity_summary"]["level"] == "verified"
    assert "agent_response" not in out
    assert len(store.rows) == 1


async def test_without_commerce_nothing_is_attempted(fake_deps, store: Store) -> None:
    out = await make_resolve_identity_node(fake_deps)(_turn("pedido 1001 ana@tienda.com"))
    assert store.rows == []
    assert "agent_response" not in out


async def test_simulator_turns_do_not_touch_identity_checks(
    fake_deps, monkeypatch: pytest.MonkeyPatch, store: Store
) -> None:
    _commerce(monkeypatch)
    state = _turn("pedido 1001 ana@tienda.com")
    state["simulation_mode"] = True
    await make_resolve_identity_node(fake_deps)(state)
    assert store.rows == []


async def test_simulator_chat_identity_runs_guest_and_has_no_sender(
    fake_deps, monkeypatch: pytest.MonkeyPatch, store: Store
) -> None:
    """El escenario con identidad "chat" se comporta como el visitante de un chat: el email
    del perfil sintético no vale como remitente y el par número + email corre `guest`."""
    _commerce(monkeypatch)
    state = _turn("pedido 1001 ana@tienda.com")
    state.update(
        simulation_mode=True,
        simulation_identity="chat",
        end_customer={"email": "sim@simulator.auyan.internal"},
    )
    out = await make_resolve_identity_node(fake_deps)(state)
    assert [(g.level, g.method) for g in _grants(out)] == [("guest", "order_contact")]
    assert len(store.rows) == 1


@pytest.mark.parametrize("failing", ["load", "write"])
async def test_identity_checks_failure_keeps_the_verified_sender_and_grants_no_guest(
    fake_deps,
    monkeypatch: pytest.MonkeyPatch,
    store: Store,
    caplog: pytest.LogCaptureFixture,
    failing: str,
) -> None:
    _commerce(monkeypatch)
    boom = AsyncMock(side_effect=RuntimeError("relation identity_checks does not exist"))
    if failing == "load":
        monkeypatch.setattr(f"{NODE}.load_guest_grants", boom)
    else:
        monkeypatch.setattr("apps.api.services.identity_guest.insert_guest_check", boom)
    state = _turn("pedido 1001 ana@tienda.com", email="luis@tienda.com", channel="email")
    with caplog.at_level("ERROR"):
        out = await make_resolve_identity_node(fake_deps)(state)
    assert "error" not in out
    assert out["identity_summary"] == {"level": "verified", "methods": ["sender_email"]}
    assert [g.level for g in _grants(out)] == ["verified"]
    assert out["identity_error"] == "RuntimeError"
    assert "agent_response" not in out
    assert any(r.message == "guest_identity_failed" for r in caplog.records)


async def test_identity_checks_failure_never_grants_guest_to_an_anonymous_chat(
    fake_deps, monkeypatch: pytest.MonkeyPatch, store: Store
) -> None:
    _commerce(monkeypatch)
    monkeypatch.setattr(
        "apps.api.services.identity_guest.insert_guest_check",
        AsyncMock(side_effect=TimeoutError("db")),
    )
    out = await make_resolve_identity_node(fake_deps)(_turn("pedido 1001 ana@tienda.com"))
    assert _grants(out) == ()
    assert out["identity_summary"]["level"] is None
    assert "agent_response" not in out


INTERNAL_IDENTITY_TERMS = re.compile(
    r"invitad|\bguest\b|\bverified\b|\bgrants?\b|\bnivel|verific", re.I
)


def _identity_part_of_the_prompt(out: dict[str, Any]) -> str:
    """Lo que la identidad aporta al bloque volátil, sin las cabeceras fijas del builder."""
    return "\n".join(part for part in (out["identity_note"], out.get("known_facts")) if part)


async def test_what_the_llm_reads_about_a_guest_has_no_internal_jargon(
    fake_deps, monkeypatch: pytest.MonkeyPatch, store: Store
) -> None:
    """#334: con un grant guest el agente le dijo al cliente "como accediste como invitado".
    Ni la nota de identidad ni el bloque de datos nombran niveles ni el proceso: dicen qué
    puede hacer el cliente para cambiar la dirección."""
    _commerce(monkeypatch)
    resolve = make_resolve_identity_node(fake_deps)
    granting_turn = await resolve(_turn("Hola, ¿dónde está mi pedido #1001?", "Ana@Tienda.com"))
    assert [g.level for g in _grants(granting_turn)] == ["guest"]

    stored = (Grant("guest", "order_contact", order_id=9001, valid_until=None),)
    monkeypatch.setattr(f"{NODE}.load_guest_grants", AsyncMock(return_value=stored))
    next_turn = await resolve(
        _turn("Quiero cambiar la dirección de envío del pedido #1001 a Calle Mayor 5")
    )
    assert next_turn["identity_summary"]["level"] == "guest"

    for out in (granting_turn, next_turn):
        prompt = _identity_part_of_the_prompt(out)
        assert INTERNAL_IDENTITY_TERMS.findall(prompt) == []
        assert "desde el email o el teléfono de la compra" in prompt
        assert "no le expliques al cliente cómo se ha comprobado quién es" in prompt


def test_routing_after_resolve_identity() -> None:
    assert route_after_resolve_identity({}) == "select_aop"
    assert route_after_resolve_identity({"decision": "respond", "agent_response": "t"}) == "respond"


# ─── Qué permite cada nivel ───────────────────────────────────────────────────


def _guest_state(order_id: int) -> dict[str, Any]:
    state = identity_state(channel="zendesk")
    guest = Grant("guest", "order_contact", order_id=order_id)
    state["identity"] = IdentityContext((guest,)).to_state()
    return state


@pytest.mark.parametrize(
    ("skill", "inputs", "blocked"),
    [
        (GetOrderStatus, {"order_identifier": "1001"}, None),
        (TagOrder, {"order_id": 1001}, None),
        (CancelOrder, {"order_id": 1001}, None),
        (UpdateShippingAddress, {"order_id": 1001}, "verified_required"),
        (GetOrderStatus, {"order_identifier": "1002"}, "identity_required"),
        (CancelOrder, {"order_id": 1002}, "identity_required"),
    ],
)
async def test_guest_gate_table(
    monkeypatch: pytest.MonkeyPatch, skill: Any, inputs: dict[str, Any], blocked: str | None
) -> None:
    _commerce(monkeypatch)
    result = await execute_skill._identity_gate(_guest_state(9001), skill, inputs)
    assert (result[0] if result else None) == blocked


async def test_guest_cannot_list_my_orders(monkeypatch: pytest.MonkeyPatch) -> None:
    _commerce(monkeypatch)
    result = await execute_skill._identity_gate(_guest_state(9001), ListMyOrders, {})
    assert result is not None and result[0] == "identity_required"


def test_update_shipping_address_still_requires_verified() -> None:
    assert UpdateShippingAddress.min_level == "verified"
    assert UpdateShippingAddress.identity_scope == "order"


# ─── Skill de respaldo ────────────────────────────────────────────────────────


def _skill_node(fake_deps: Any) -> Any:
    return make_execute_skill_node(fake_deps)


def _call(order: str, contact: str, state: dict[str, Any]) -> dict[str, Any]:
    state.update(
        pending_tool_call={
            "id": "t1",
            "slug": CHECK,
            "input": {"order_number": order, "contact": contact},
        },
        tool_permissions={},
        allowed_skills=[],
        claim_salt=SALT,
    )
    return state


@pytest.fixture
def skill_db(monkeypatch: pytest.MonkeyPatch, store: Store) -> None:
    # Otros tests recargan módulos: se parchea el módulo al que la clase está atada.
    monkeypatch.setitem(
        CheckOrderContact.execute.__globals__, "tenant_scope", make_fake_tenant_scope()
    )


ORDER_SLUGS = ["shopify.get_order_status", "shopify.cancel_order"]
ENABLED = {slug: {"is_enabled": True} for slug in [*ORDER_SLUGS, "shopify.get_product_info"]}


async def test_the_fallback_skill_is_offered_only_on_order_aops_without_a_grant() -> None:
    assert SkillRegistry.is_core(CHECK)
    assert not SkillRegistry.is_core("shopify.get_order_status")
    none = IdentityContext()

    def offered(
        slugs: list[str],
        identity: IdentityContext,
        capabilities: frozenset[CommerceCapability] | None = ALL_CAPABILITIES,
    ) -> bool:
        return CHECK in visible_skills(slugs, ENABLED, identity, capabilities=capabilities)

    assert offered(ORDER_SLUGS, none)
    assert not offered(ORDER_SLUGS, none, capabilities=None)
    assert not offered(ORDER_SLUGS, none, capabilities=frozenset())
    assert not offered(["shopify.get_product_info"], none)
    assert not offered([], none)
    assert not offered(ORDER_SLUGS, IdentityContext((Grant("guest", "order_contact", order_id=1),)))
    assert not offered(ORDER_SLUGS, sender_identity(IdentityEvidence(email="a@x.com"), salt=SALT))


async def test_non_order_aops_keep_the_cheap_model_path() -> None:
    only_product = ["shopify.get_product_info"]
    everything = ALL_CAPABILITIES
    assert visible_skills(only_product, ENABLED, IdentityContext(), capabilities=everything) == (
        only_product
    )
    assert visible_skills([], ENABLED, IdentityContext(), capabilities=everything) == []


async def test_the_fallback_skill_grants_guest_and_updates_the_turn(
    fake_deps, monkeypatch: pytest.MonkeyPatch, skill_db: None
) -> None:
    _commerce(monkeypatch)
    out = await _skill_node(fake_deps)(_call("1001", "Ana@Tienda.com", identity_state()))
    assert out["tool_results"][0]["output"]["verified"] is True
    assert [g.level for g in _grants(out)] == ["guest"]
    assert out["identity_summary"]["level"] == "guest"
    assert "cambiar la dirección de envío" in out["identity_note"]
    assert "#1001" in out["known_facts"]
    assert "decision" not in out


async def test_the_fallback_skill_escalates_when_the_store_is_down(
    fake_deps, monkeypatch: pytest.MonkeyPatch, skill_db: None
) -> None:
    _commerce(monkeypatch, _adapter(fail=True))
    out = await _skill_node(fake_deps)(_call("1001", "ana@tienda.com", identity_state()))
    assert out["decision"] == "escalate"
    assert out["agent_response"] == fixed_text("commerce_unavailable", "es")
    assert out["escalation_reason"].startswith("commerce_unavailable:")


async def test_the_fallback_skill_failure_ends_with_the_same_fixed_text(
    fake_deps, monkeypatch: pytest.MonkeyPatch, skill_db: None
) -> None:
    _commerce(monkeypatch)
    out = await _skill_node(fake_deps)(_call("1002", "ana@tienda.com", identity_state()))
    assert out["decision"] == "respond"
    assert out["agent_response"] == fixed_text("guest_not_verified", "es")
    assert out["tool_results"][0]["output"]["order"] is None
    assert route_after_execute_skill({**out, "error": None}) == "respond"


async def test_the_fallback_skill_obeys_the_same_limit(
    fake_deps, monkeypatch: pytest.MonkeyPatch, skill_db: None, store: Store
) -> None:
    _commerce(monkeypatch)
    node = _skill_node(fake_deps)
    for i in range(5):
        await node(_call(str(8000 + i), "ana@tienda.com", identity_state()))
    out = await node(_call("1001", "ana@tienda.com", identity_state()))
    assert out["agent_response"] == fixed_text("guest_locked", "es")
    assert len(store.rows) == 5


async def test_the_fallback_skill_does_not_need_the_aop_or_tenant_permissions(
    fake_deps, monkeypatch: pytest.MonkeyPatch, skill_db: None
) -> None:
    _commerce(monkeypatch)
    out = await _skill_node(fake_deps)(_call("1001", "ana@tienda.com", identity_state()))
    assert out["tool_results"][0]["is_error"] is False, out["tool_results"][0]["error"]
