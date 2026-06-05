"""Tests de los AOPs canónicos + su provisioning.

Cubren los invariantes que NO pueden romperse porque son los defaults de plataforma
que hereda cada tenant:
  - los 8 AOPs esperados, slugs únicos
  - cada allowed_skill está registrada (caza typos)
  - `default` es SOLO LECTURA (invariante de seguridad: el fallback no tiene tijeras)
  - los permisos cubren todas las skills usadas; L3 con approval, L1/L2 sin él
  - raw_source round-trippea con el parser del editor del dashboard
  - cada AOP compila
  - provision_canonical_aops: crea 8 + 11 permisos, idempotente, y propaga con --update
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

# Importar dispara el registro de las skills Shopify en SkillRegistry.
import apps.api.skills.shopify  # noqa: F401
import pytest
import yaml
from apps.api.aops import canonical
from apps.api.aops.canonical import (
    CANONICAL_AOPS,
    CANONICAL_TOOL_PERMISSIONS,
    _build_raw_source,
    provision_canonical_aops,
)
from apps.api.aops.compiler import compile_aop
from apps.api.db.models import AopWithContent, TenantConfiguration
from apps.api.skills.registry import SkillRegistry

EXPECTED_SLUGS = {
    "order_status",
    "shipping_info",
    "returns",
    "refunds",
    "product_info",
    "order_change",
    "complaint",
    "default",
}


@pytest.fixture(autouse=True)
def _ensure_shopify_skills_registered():
    """Otros tests (test_execute_skill_node, test_graph_e2e) llaman SkillRegistry._reset()
    y dejan el registro global vacío. Re-registramos las skills Shopify antes de cada test
    recargando sus submódulos (re-ejecuta los @SkillRegistry.register), y restauramos al
    terminar para no contaminar a otros tests."""
    import importlib

    saved = dict(SkillRegistry._by_slug)
    for name in (
        "add_order_note",
        "cancel_order",
        "get_customer_history",
        "get_order_by_email",
        "get_order_status",
        "get_product_info",
        "get_shop_policies",
        "refund_partial",
        "start_return",
        "tag_order",
        "update_shipping_address",
    ):
        importlib.reload(importlib.import_module(f"apps.api.skills.shopify.{name}"))
    yield
    SkillRegistry._by_slug.clear()
    SkillRegistry._by_slug.update(saved)


# ─── Integridad de los datos ───────────────────────────────────────────────────


def test_exactly_eight_canonical_aops_unique():
    slugs = [a["slug"] for a in CANONICAL_AOPS]
    assert len(slugs) == 8
    assert set(slugs) == EXPECTED_SLUGS
    assert len(slugs) == len(set(slugs)), "hay slugs duplicados"


def test_frontmatter_required_keys():
    for a in CANONICAL_AOPS:
        fm = a["frontmatter"]
        assert fm["slug"] == a["slug"], f"slug del frontmatter != slug en {a['slug']}"
        assert fm["name"]
        assert fm["workspace"] == "production"
        assert fm["triggers"]["description"].strip()
        assert isinstance(fm["allowed_skills"], list) and fm["allowed_skills"]
        assert isinstance(fm["max_tool_iterations"], int) and fm["max_tool_iterations"] > 0
        assert 0.0 <= fm["confidence_threshold"] <= 1.0
        assert isinstance(fm["require_supervision"], bool)
        assert isinstance(fm["escalation_triggers"], list) and fm["escalation_triggers"]
        assert a["body"].strip()


def test_all_allowed_skills_are_registered():
    """Caza typos en slugs de skills — si una no existe, compile la omitiría en silencio."""
    for a in CANONICAL_AOPS:
        for slug in a["frontmatter"]["allowed_skills"]:
            SkillRegistry.get(slug)  # ValueError si no está registrada


def test_default_is_read_only():
    """INVARIANTE DE SEGURIDAD: el fallback `default` no puede tener skills de escritura.

    Si la confianza del clasificador es baja, cae a `default`; ese AOP NUNCA debe poder
    cancelar/reembolsar/cambiar. Solo L1 (lectura).
    """
    default = next(a for a in CANONICAL_AOPS if a["slug"] == "default")
    for slug in default["frontmatter"]["allowed_skills"]:
        tier = SkillRegistry.get(slug).tier
        assert tier == "L1", f"`default` no puede incluir {slug} ({tier}); debe ser solo L1"


def test_tool_permissions_cover_every_used_skill():
    """execute_skill rechaza skills sin permiso enabled — TODAS las usadas deben tener row."""
    used = {s for a in CANONICAL_AOPS for s in a["frontmatter"]["allowed_skills"]}
    granted = {p["skill_slug"] for p in CANONICAL_TOOL_PERMISSIONS}
    missing = used - granted
    assert not missing, f"skills usadas por AOPs sin permiso default: {missing}"


def test_permission_posture_l3_requires_approval():
    """L1/L2 autónomos (sin approval); L3 enabled pero con human_approval_required."""
    for p in CANONICAL_TOOL_PERMISSIONS:
        tier = SkillRegistry.get(p["skill_slug"]).tier
        assert p["is_enabled"] is True, f"{p['skill_slug']} debería nacer enabled"
        if tier == "L3":
            assert p["human_approval_required"] is True, (
                f"{p['skill_slug']} es L3 y debe requerir approval por defecto"
            )
        else:
            assert p["human_approval_required"] is False, (
                f"{p['skill_slug']} es {tier} y no debería requerir approval"
            )


def test_no_hardcoded_tenant_constants():
    """Los canónicos son tenant-agnósticos: nada de '30 días' ni 'EUR' en frontmatter/body."""
    for a in CANONICAL_AOPS:
        blob = (yaml.safe_dump(a["frontmatter"], allow_unicode=True) + a["body"]).lower()
        assert "30 días" not in blob, f"{a['slug']} hardcodea un plazo"
        assert "eur" not in blob, f"{a['slug']} hardcodea una moneda"


# ─── raw_source editable (round-trip con el parser del dashboard) ───────────────


def test_raw_source_round_trips():
    """_build_raw_source debe parsearse de vuelta igual (mismo split que routers/aops.py)."""
    for a in CANONICAL_AOPS:
        raw = _build_raw_source(a["frontmatter"], a["body"])
        assert raw.startswith("---")
        parts = raw.split("---", 2)
        assert len(parts) == 3, f"formato frontmatter inválido en {a['slug']}"
        parsed_fm = yaml.safe_load(parts[1])
        parsed_body = parts[2].strip()
        assert parsed_fm == a["frontmatter"], f"frontmatter no round-trippea en {a['slug']}"
        assert parsed_body == a["body"].strip(), f"body no round-trippea en {a['slug']}"


# ─── Compilación ────────────────────────────────────────────────────────────────


def test_every_aop_compiles():
    tenant_id = uuid4()
    tc = TenantConfiguration(
        tenant_id=tenant_id,
        agent_model="claude-sonnet-4-6",
        escalation_threshold=0.7,
    )
    for a in CANONICAL_AOPS:
        fm = a["frontmatter"]
        awc = AopWithContent(
            id=uuid4(),
            tenant_id=tenant_id,
            slug=a["slug"],
            workspace="production",
            current_version=1,
            yaml_frontmatter=fm,
            body_markdown=a["body"],
            raw_source=_build_raw_source(fm, a["body"]),
        )
        compiled = compile_aop(awc, tc)
        assert compiled.system_prompt.strip()
        assert compiled.allowed_skills == fm["allowed_skills"]
        assert compiled.max_iterations == fm["max_tool_iterations"]
        assert compiled.confidence_threshold == fm["confidence_threshold"]
        assert compiled.require_supervision == fm["require_supervision"]
        # Todas las allowed_skills resuelven a tool definitions (no se omite ninguna).
        assert len(compiled.tool_definitions) == len(fm["allowed_skills"])


def test_order_change_prompt_instructs_address_readback():
    """order_change debe instruir leer la dirección parseada y esperar confirmación
    del cliente antes de update_shipping_address (hallazgo 5 del dogfood): un error
    de transcripción no debe llegar a aprobación sin validarse con el cliente."""
    tenant_id = uuid4()
    tc = TenantConfiguration(
        tenant_id=tenant_id, agent_model="claude-sonnet-4-6", escalation_threshold=0.7
    )
    a = next(x for x in CANONICAL_AOPS if x["slug"] == "order_change")
    fm = a["frontmatter"]
    awc = AopWithContent(
        id=uuid4(),
        tenant_id=tenant_id,
        slug="order_change",
        workspace="production",
        current_version=1,
        yaml_frontmatter=fm,
        body_markdown=a["body"],
        raw_source=_build_raw_source(fm, a["body"]),
    )
    prompt = compile_aop(awc, tc).system_prompt.lower()
    assert "confirme que es correcta" in prompt
    assert "espera su confirmación" in prompt
    # No instruye saltarse la confirmación (consistente con el guardrail adversarial).
    assert "sin confirmación" not in prompt


def test_order_change_prompt_minimizes_address_friction():
    """order_change no debe pedir país ni provincia a ciegas cuando el CP/tienda los
    determinan (hallazgo 6): asume el país de la tienda y deduce la provincia del CP,
    confirmándolos en el read-back en vez de preguntarlos campo por campo."""
    tenant_id = uuid4()
    tc = TenantConfiguration(
        tenant_id=tenant_id, agent_model="claude-sonnet-4-6", escalation_threshold=0.7
    )
    a = next(x for x in CANONICAL_AOPS if x["slug"] == "order_change")
    fm = a["frontmatter"]
    awc = AopWithContent(
        id=uuid4(),
        tenant_id=tenant_id,
        slug="order_change",
        workspace="production",
        current_version=1,
        yaml_frontmatter=fm,
        body_markdown=a["body"],
        raw_source=_build_raw_source(fm, a["body"]),
    )
    prompt = compile_aop(awc, tc).system_prompt.lower()
    # El país se conserva del pedido; no se pide ni se envía salvo cambio explícito.
    assert "no envíes el campo `country`" in prompt
    assert "deduce la provincia" in prompt
    # Sigue prohibido inventar.
    assert "nunca inventes" in prompt


def test_order_change_prompt_no_respawn_after_approval():
    """order_change no debe re-ejecutar la skill ante agradecimientos/cortesías una
    vez que la acción quedó en aprobación (hallazgo 7): evita approvals duplicados
    huérfanos. Solo repite si el cliente pide una acción nueva o distinta."""
    tenant_id = uuid4()
    tc = TenantConfiguration(
        tenant_id=tenant_id, agent_model="claude-sonnet-4-6", escalation_threshold=0.7
    )
    a = next(x for x in CANONICAL_AOPS if x["slug"] == "order_change")
    fm = a["frontmatter"]
    awc = AopWithContent(
        id=uuid4(),
        tenant_id=tenant_id,
        slug="order_change",
        workspace="production",
        current_version=1,
        yaml_frontmatter=fm,
        body_markdown=a["body"],
        raw_source=_build_raw_source(fm, a["body"]),
    )
    prompt = compile_aop(awc, tc).system_prompt.lower()
    assert "no vuelvas a llamar la skill" in prompt
    assert "acción nueva o distinta" in prompt


def test_returns_prompt_measures_window_from_delivery():
    """El plazo de devolución se mide desde la recepción (delivered_at → fulfilled_at
    → created_at), no desde la compra (H4): created_at solo como último recurso."""
    tenant_id = uuid4()
    tc = TenantConfiguration(
        tenant_id=tenant_id, agent_model="claude-sonnet-4-6", escalation_threshold=0.7
    )
    a = next(x for x in CANONICAL_AOPS if x["slug"] == "returns")
    fm = a["frontmatter"]
    awc = AopWithContent(
        id=uuid4(),
        tenant_id=tenant_id,
        slug="returns",
        workspace="production",
        current_version=1,
        yaml_frontmatter=fm,
        body_markdown=a["body"],
        raw_source=_build_raw_source(fm, a["body"]),
    )
    prompt = compile_aop(awc, tc).system_prompt.lower()
    assert "desde la recepción" in prompt
    assert "delivered_at" in prompt
    assert "fulfilled_at" in prompt


# ─── provision_canonical_aops ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_provision_creates_eight_aops_and_all_permissions(monkeypatch):
    created_slugs: list[str] = []
    perms: list[tuple[str, bool, bool]] = []

    async def fake_get(conn, tenant_id, slug, workspace):
        return None  # ninguno existe

    async def fake_create(conn, *, tenant_id, slug, workspace, yaml_frontmatter, body_markdown, raw_source, created_by=None):
        created_slugs.append(slug)
        return SimpleNamespace(id=uuid4())

    async def fake_save(*args, **kwargs):
        raise AssertionError("no debe actualizar cuando el AOP no existe")

    async def fake_upsert(conn, *, tenant_id, skill_slug, is_enabled, human_approval_required=False, threshold_override=None, enabled_by=None):
        perms.append((skill_slug, is_enabled, human_approval_required))
        return SimpleNamespace()

    monkeypatch.setattr(canonical, "get_aop_by_slug", fake_get)
    monkeypatch.setattr(canonical, "create_aop", fake_create)
    monkeypatch.setattr(canonical, "save_aop_version", fake_save)
    monkeypatch.setattr(canonical, "upsert_tool_permission", fake_upsert)

    result = await provision_canonical_aops(AsyncMock(), uuid4())

    assert result["created"] == 8
    assert result["updated"] == 0
    assert result["skipped"] == 0
    assert set(created_slugs) == EXPECTED_SLUGS
    assert len(perms) == len(CANONICAL_TOOL_PERMISSIONS) == 11


@pytest.mark.asyncio
async def test_provision_idempotent_skips_existing(monkeypatch):
    async def fake_get(conn, tenant_id, slug, workspace):
        return SimpleNamespace(id=uuid4())  # ya existe

    async def fake_create(*args, **kwargs):
        raise AssertionError("no debe crear cuando el AOP ya existe")

    async def fake_save(*args, **kwargs):
        raise AssertionError("no debe actualizar sin update_existing")

    async def fake_upsert(*args, **kwargs):
        return SimpleNamespace()

    monkeypatch.setattr(canonical, "get_aop_by_slug", fake_get)
    monkeypatch.setattr(canonical, "create_aop", fake_create)
    monkeypatch.setattr(canonical, "save_aop_version", fake_save)
    monkeypatch.setattr(canonical, "upsert_tool_permission", fake_upsert)

    result = await provision_canonical_aops(AsyncMock(), uuid4())

    assert result["created"] == 0
    assert result["skipped"] == 8
    # los permisos se hacen upsert igual (idempotente)
    assert result["tool_permissions"] == 11


@pytest.mark.asyncio
async def test_provision_update_existing_creates_new_versions(monkeypatch):
    saved_slugs: list[str] = []

    async def fake_get(conn, tenant_id, slug, workspace):
        return SimpleNamespace(id=uuid4())

    async def fake_create(*args, **kwargs):
        raise AssertionError("no debe crear cuando el AOP ya existe")

    async def fake_save(conn, *, tenant_id, aop_id, yaml_frontmatter, body_markdown, raw_source, created_by=None):
        saved_slugs.append(yaml_frontmatter["slug"])
        return SimpleNamespace()

    async def fake_upsert(*args, **kwargs):
        return SimpleNamespace()

    monkeypatch.setattr(canonical, "get_aop_by_slug", fake_get)
    monkeypatch.setattr(canonical, "create_aop", fake_create)
    monkeypatch.setattr(canonical, "save_aop_version", fake_save)
    monkeypatch.setattr(canonical, "upsert_tool_permission", fake_upsert)

    result = await provision_canonical_aops(AsyncMock(), uuid4(), update_existing=True)

    assert result["updated"] == 8
    assert result["created"] == 0
    assert set(saved_slugs) == EXPECTED_SLUGS
