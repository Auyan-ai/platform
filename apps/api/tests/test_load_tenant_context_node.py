"""Tests del nodo `load_tenant_context`."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from apps.api.agents.nodes.load_tenant_context import make_load_tenant_context_node

from tests.conftest import (
    TENANT_ID,
    make_fake_tenant_scope,
    make_tenant,
    make_tenant_configuration,
)

MODULE = "apps.api.agents.nodes.load_tenant_context"


def _state() -> dict:
    return {"tenant_id": str(TENANT_ID)}


def _patch_module(
    monkeypatch,
    *,
    tenant,
    config,
    system_prompt,
    commerce_ctx=None,
    playbook=None,
    facts=None,
    returns_policy=None,
    kb_rows=(),
) -> None:
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.get_tenant_by_id", AsyncMock(return_value=tenant))
    monkeypatch.setattr(f"{MODULE}.get_tenant_configuration", AsyncMock(return_value=config))
    monkeypatch.setattr(f"{MODULE}.get_active_system_prompt", AsyncMock(return_value=system_prompt))
    monkeypatch.setattr(f"{MODULE}.list_tool_permissions", AsyncMock(return_value=[]))
    monkeypatch.setattr(f"{MODULE}.get_tenant_playbook", AsyncMock(return_value=playbook))
    monkeypatch.setattr(f"{MODULE}.get_tenant_facts", AsyncMock(return_value=facts))
    monkeypatch.setattr(
        f"{MODULE}.load_current_returns_policy", AsyncMock(return_value=returns_policy)
    )
    monkeypatch.setattr(
        f"{MODULE}.list_kb_documents_for_context", AsyncMock(return_value=list(kb_rows))
    )
    monkeypatch.setattr(
        f"{MODULE}.build_commerce_integration_ctx",
        AsyncMock(return_value=commerce_ctx),
    )


@pytest.mark.asyncio
async def test_happy_path(fake_deps, monkeypatch) -> None:
    _patch_module(
        monkeypatch,
        tenant=make_tenant(),
        config=make_tenant_configuration(agent_model="claude-opus-4-7"),
        system_prompt="Eres el agente de Acme.",
    )
    node = make_load_tenant_context_node(fake_deps)

    out = await node(_state())

    assert out["system_prompt"] == "Eres el agente de Acme."
    assert out["model_used"] == "claude-opus-4-7"
    assert out["tenant_config"]["escalation_threshold"] == 0.70
    assert "error" not in out


@pytest.mark.asyncio
async def test_agent_model_without_capabilities_row_falls_back_to_the_default(
    fake_deps, monkeypatch, caplog
) -> None:
    """`tenant_configurations.agent_model` se escribe por SQL: un ID sin fila (alias, typo)
    no tumba los turnos del tenant ni se cobra a tarifa máxima. Corre el modelo por defecto
    y queda un error con el tenant y el ID."""
    from apps.api.core.config import get_models

    _patch_module(
        monkeypatch,
        tenant=make_tenant(),
        config=make_tenant_configuration(agent_model="claude-haiku-4-5"),
        system_prompt="Eres el agente de Acme.",
    )
    node = make_load_tenant_context_node(fake_deps)

    with caplog.at_level("ERROR"):
        out = await node(_state())

    assert out["model_used"] == get_models().default_agent_model
    assert any(
        "tenant_agent_model_unsupported" in r.getMessage() and "claude-haiku-4-5" in r.getMessage()
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_tenant_not_found(fake_deps, monkeypatch) -> None:
    _patch_module(monkeypatch, tenant=None, config=None, system_prompt=None)
    node = make_load_tenant_context_node(fake_deps)

    out = await node(_state())

    assert out["error"] == "tenant_not_found"


@pytest.mark.asyncio
async def test_tenant_inactive(fake_deps, monkeypatch) -> None:
    _patch_module(
        monkeypatch,
        tenant=make_tenant(status="suspended"),
        config=make_tenant_configuration(),
        system_prompt="x",
    )
    node = make_load_tenant_context_node(fake_deps)

    out = await node(_state())

    assert out["error"].startswith("tenant_not_active")
    assert "suspended" in out["error"]


@pytest.mark.asyncio
async def test_config_missing(fake_deps, monkeypatch) -> None:
    _patch_module(
        monkeypatch,
        tenant=make_tenant(),
        config=None,
        system_prompt="x",
    )
    node = make_load_tenant_context_node(fake_deps)

    out = await node(_state())

    assert out["error"] == "tenant_config_missing"


@pytest.mark.asyncio
async def test_no_active_system_prompt(fake_deps, monkeypatch) -> None:
    _patch_module(
        monkeypatch,
        tenant=make_tenant(),
        config=make_tenant_configuration(),
        system_prompt=None,
    )
    node = make_load_tenant_context_node(fake_deps)

    out = await node(_state())

    assert out["error"] == "no_active_system_prompt"


@pytest.mark.asyncio
async def test_empty_system_prompt_treated_as_missing(fake_deps, monkeypatch) -> None:
    """Un prompt activo pero con contenido vacío es un dato corrupto, escala."""
    _patch_module(
        monkeypatch,
        tenant=make_tenant(),
        config=make_tenant_configuration(),
        system_prompt="",
    )
    node = make_load_tenant_context_node(fake_deps)

    out = await node(_state())

    assert out["error"] == "no_active_system_prompt"


# ---------------------------------------------------------------------------
# commerce_integration_ctx — el nodo delega en build_commerce_integration_ctx
# y serializa el IntegrationContext resultante al state. La lógica de cripto
# (descifrado, token exchange, fallback) se prueba en test_commerce_context.py.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_commerce_integration_returns_none(fake_deps, monkeypatch) -> None:
    """Helper devuelve None (sin integración ni creds) → ctx es None."""
    _patch_module(
        monkeypatch,
        tenant=make_tenant(),
        config=make_tenant_configuration(),
        system_prompt="ok",
        commerce_ctx=None,
    )
    node = make_load_tenant_context_node(fake_deps)

    out = await node(_state())

    assert out["commerce_integration_ctx"] is None


@pytest.mark.asyncio
async def test_serializes_commerce_ctx_to_dict(fake_deps, monkeypatch) -> None:
    """Helper devuelve IntegrationContext → el nodo lo serializa JSON-safe al state."""
    from apps.api.integrations.base import IntegrationContext

    ctx = IntegrationContext(
        tenant_id=TENANT_ID,
        credentials={"domain": "tenant-a.myshopify.com", "access_token": "shpat_x"},
        config={"shop_name": "Tenant A"},
    )
    _patch_module(
        monkeypatch,
        tenant=make_tenant(),
        config=make_tenant_configuration(),
        system_prompt="ok",
        commerce_ctx=ctx,
    )
    node = make_load_tenant_context_node(fake_deps)

    out = await node(_state())

    result = out["commerce_integration_ctx"]
    assert result == {
        "tenant_id": str(TENANT_ID),
        "credentials": {"domain": "tenant-a.myshopify.com", "access_token": "shpat_x"},
        "config": {"shop_name": "Tenant A"},
    }
    assert isinstance(result["tenant_id"], str)  # UUID serializado a str para el state


# ---------------------------------------------------------------------------
# tenant_playbook + tenant_facts — cargados por load_tenant_context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_playbook_and_facts_loaded_when_present(fake_deps, monkeypatch) -> None:
    from apps.api.db.models import TenantFacts, TenantPlaybook

    playbook = TenantPlaybook(
        tenant_id=TENANT_ID,
        brand_voice="Amigable y cercano",
        policies="30 días para devoluciones",
    )
    facts = TenantFacts(
        tenant_id=TENANT_ID,
        data={"business_hours": "L-V 9-18", "support_email": "hola@tienda.com"},
    )
    _patch_module(
        monkeypatch,
        tenant=make_tenant(),
        config=make_tenant_configuration(),
        system_prompt="ok",
        playbook=playbook,
        facts=facts,
    )
    node = make_load_tenant_context_node(fake_deps)
    out = await node(_state())

    assert out["tenant_playbook"]["brand_voice"] == "Amigable y cercano"
    assert out["tenant_playbook"]["policies"] == "30 días para devoluciones"
    assert out["tenant_facts"] == {"business_hours": "L-V 9-18", "support_email": "hola@tienda.com"}


@pytest.mark.asyncio
async def test_playbook_and_facts_none_when_not_configured(fake_deps, monkeypatch) -> None:
    """Tenant recién creado sin onboarding: playbook y facts son None."""
    _patch_module(
        monkeypatch,
        tenant=make_tenant(),
        config=make_tenant_configuration(),
        system_prompt="ok",
        playbook=None,
        facts=None,
    )
    node = make_load_tenant_context_node(fake_deps)
    out = await node(_state())

    assert out["tenant_playbook"] is None
    assert out["tenant_facts"] is None


_POLICY = {
    "schema_version": 1,
    "window": {"days": 30, "starts_at": "delivery"},
    "reasons": [
        {"code": "too_small", "label": "Pequeña", "fault": "customer", "required_evidence": []}
    ],
    "shipping": {
        "method": "customer_ships",
        "return_address": "Calle Mayor 1, Madrid",
        "payer": {"store_fault": "store", "customer_fault": "customer"},
    },
    "refund_days": 14,
    "refund_method": "original_payment",
    "restocking_fee_percent": {"store_fault": "0", "customer_fault": "0"},
    "excluded_product_tags": [],
    "exchanges": {"enabled": False},
    "returns_require_approval": True,
    "evidence_requires_approval": True,
}


@pytest.mark.asyncio
async def test_returns_policy_is_loaded_with_its_version(fake_deps, monkeypatch) -> None:
    from datetime import UTC, datetime

    from apps.api.db.returns_policy import StoredPolicy

    _patch_module(
        monkeypatch,
        tenant=make_tenant(),
        config=make_tenant_configuration(),
        system_prompt="ok",
        returns_policy=StoredPolicy(
            version=4, policy=_POLICY, edited_by_email=None, created_at=datetime.now(UTC)
        ),
    )

    out = await make_load_tenant_context_node(fake_deps)(_state())

    assert out["returns_policy"]["version"] == 4
    assert out["returns_policy"]["policy"]["window"] == {"days": 30, "starts_at": "delivery"}


@pytest.mark.asyncio
async def test_unreadable_or_missing_policy_is_none(fake_deps, monkeypatch) -> None:
    from datetime import UTC, datetime

    from apps.api.db.returns_policy import StoredPolicy

    _patch_module(
        monkeypatch,
        tenant=make_tenant(),
        config=make_tenant_configuration(),
        system_prompt="ok",
        returns_policy=StoredPolicy(
            version=2,
            policy={**_POLICY, "schema_version": 9},
            edited_by_email=None,
            created_at=datetime.now(UTC),
        ),
    )

    out = await make_load_tenant_context_node(fake_deps)(_state())

    assert out["returns_policy"] is None


@pytest.mark.asyncio
async def test_a_simulator_scenario_fixes_its_own_policy(fake_deps, monkeypatch) -> None:
    _patch_module(
        monkeypatch, tenant=make_tenant(), config=make_tenant_configuration(), system_prompt="ok"
    )
    node = make_load_tenant_context_node(fake_deps)
    sim = {**_state(), "simulation_mode": True}

    with_policy = await node({**sim, "simulation_fixtures": {"returns_policy": _POLICY}})
    without = await node({**sim, "simulation_fixtures": {"returns_policy": None}})

    assert with_policy["returns_policy"] == {"version": 0, "policy": _POLICY}
    assert without["returns_policy"] is None


def _kb_row(title: str, content: str | None, chars: int | None = None) -> dict:
    return {
        "title": title,
        "source": f"https://x.es/{title}",
        "chars": len(content or "") if chars is None else chars,
        "content": content,
    }


@pytest.mark.asyncio
async def test_small_kb_loads_in_full_context_mode(fake_deps, monkeypatch) -> None:
    _patch_module(
        monkeypatch,
        tenant=make_tenant(),
        config=make_tenant_configuration(),
        system_prompt="Eres el agente de Acme.",
        kb_rows=[_kb_row("Envíos", "Gratis desde 110 €."), _kb_row("Devoluciones", "30 días.")],
    )
    node = make_load_tenant_context_node(fake_deps)

    out = await node(_state())

    assert out["knowledge"]["mode"] == "full_context"
    assert out["knowledge"]["doc_count"] == 2
    assert out["knowledge"]["total_tokens"] == 8  # ceil((19 + 8) / 3.5)
    assert [d["title"] for d in out["knowledge"]["documents"]] == ["Envíos", "Devoluciones"]


@pytest.mark.asyncio
async def test_large_kb_falls_back_to_retrieval_without_documents(fake_deps, monkeypatch) -> None:
    fake_deps.settings.kb_full_context_token_budget = 100
    _patch_module(
        monkeypatch,
        tenant=make_tenant(),
        config=make_tenant_configuration(),
        system_prompt="Eres el agente de Acme.",
        kb_rows=[_kb_row("Grande", None, chars=4000)],
    )
    node = make_load_tenant_context_node(fake_deps)

    out = await node(_state())

    assert out["knowledge"] == {
        "mode": "retrieval",
        "total_tokens": 1143,
        "doc_count": 1,
        "documents": [],
    }


@pytest.mark.asyncio
async def test_tenant_budget_override_beats_the_system_default(fake_deps, monkeypatch) -> None:
    """Misma KB (4000 caracteres): con el defecto del sistema cabe, con el del tenant no."""
    rows = [_kb_row("Grande", "x" * 4000)]
    _patch_module(
        monkeypatch,
        tenant=make_tenant(),
        config=make_tenant_configuration(),
        system_prompt="Eres el agente de Acme.",
        kb_rows=rows,
    )
    default_out = await make_load_tenant_context_node(fake_deps)(_state())
    _patch_module(
        monkeypatch,
        tenant=make_tenant(),
        config=make_tenant_configuration(extra={"kb_full_context_token_budget": 500}),
        system_prompt="Eres el agente de Acme.",
        kb_rows=rows,
    )

    override_out = await make_load_tenant_context_node(fake_deps)(_state())

    assert default_out["knowledge"]["mode"] == "full_context"
    assert override_out["knowledge"]["mode"] == "retrieval"
