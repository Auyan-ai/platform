"""Guards de SQL que los mocks no detectan (errores de tipos al preparar la query)."""

from __future__ import annotations

import inspect

from apps.api.db import queries


def test_upsert_tool_permission_casts_enabled_by_to_uuid() -> None:
    """$6 (enabled_by) se usa en VALUES y dentro de un CASE … ELSE NULL: sin cast
    explícito Postgres deduce `text` en uno y `uuid` en otro y rechaza la query
    SIEMPRE (AmbiguousParameterError). Rompía provision_tenant, el PUT de permisos
    y seed_canonical_aops."""
    sql = inspect.getsource(queries.upsert_tool_permission)
    assert "$6," not in sql.replace("$6::uuid,", "")
    assert "THEN $6::uuid ELSE NULL" in sql


def test_insert_tool_permission_if_missing_never_overwrites() -> None:
    """La siembra de permisos canónicos no pisa filas existentes (ni con --update)."""
    sql = inspect.getsource(queries.insert_tool_permission_if_missing)
    assert "ON CONFLICT (tenant_id, skill_slug) DO NOTHING" in sql
    assert "DO UPDATE" not in sql
    assert "$5::uuid)" in sql
