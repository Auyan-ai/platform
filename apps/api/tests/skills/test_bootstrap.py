"""Bootstrap test del paquete skills.

Garantiza que importar `apps.api.skills` popula el `SkillRegistry` con todas
las skills disponibles (vía side-effect imports en `__init__.py`). Sin esto,
el grafo en producción arranca con registry vacío y `execute_skill` siempre
devuelve `unknown_skill`.

Para validar el comportamiento real desde un estado limpio, corremos el
import en un subprocess: así no contaminamos `sys.modules` del test runner
(otros tests del módulo skills ya tienen las clases cacheadas y reciclarlas
rompería comparaciones de identidad).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

EXPECTED_SHOPIFY_SKILLS: tuple[str, ...] = (
    "shopify.get_customer_history",
    "shopify.get_order_by_email",
    "shopify.get_order_status",
    "shopify.get_product_info",
    "shopify.get_shop_policies",
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_MAIN_PATH = _REPO_ROOT / "apps" / "api" / "main.py"


def _registry_slugs_from_subprocess() -> list[str]:
    """Importa `apps.api.skills` en un proceso Python limpio y devuelve sus slugs."""
    code = (
        "import apps.api.skills\n"
        "from apps.api.skills.registry import SkillRegistry\n"
        "import json, sys\n"
        "json.dump(sorted(SkillRegistry._by_slug.keys()), sys.stdout)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def registered_slugs() -> list[str]:
    return _registry_slugs_from_subprocess()


@pytest.mark.parametrize("slug", EXPECTED_SHOPIFY_SKILLS)
def test_shopify_skill_registered_after_package_import(
    registered_slugs: list[str], slug: str
) -> None:
    assert slug in registered_slugs, (
        f"Tras `import apps.api.skills`, la skill {slug!r} debería quedar "
        f"registrada. Slugs presentes: {registered_slugs}"
    )


def test_main_module_imports_skills_package() -> None:
    text = _MAIN_PATH.read_text(encoding="utf-8")
    assert "import apps.api.skills" in text, (
        "apps/api/main.py debe importar `apps.api.skills` para popular el "
        "SkillRegistry al arrancar el API."
    )
