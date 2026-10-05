"""¿Están aplicadas las migraciones? Se deduce del esquema real, sin tabla de control.

Las migraciones se aplican a mano (psql / SQL Editor de Supabase) y no dejan rastro en
ninguna tabla. Este módulo lee `supabase/migrations/*.sql` en orden, reproduce el DDL que
deja huella comprobable (tablas, columnas añadidas, índices con nombre, tipos y valores de
enum, buckets de Storage) aplicando también los `DROP` y `RENAME` posteriores, y compara
lo que debería existir con el catálogo de Postgres.

Una migración sin huella comprobable (solo funciones, políticas RLS, constraints, datos)
se reporta como "no verificable": el doctor no inventa que está aplicada.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import asyncpg

MIGRATIONS_DIR = Path(__file__).resolve().parents[4] / "supabase" / "migrations"

ObjectKind = Literal["table", "column", "index", "type", "enum_value", "bucket"]

_IDENT = r'(?:"?public"?\.)?"?([A-Za-z_][A-Za-z0-9_]*)"?'
_TABLE_CONSTRAINT_WORDS = {"constraint", "primary", "unique", "foreign", "check", "exclude"}


@dataclass
class SchemaObject:
    """Objeto que una migración crea y que se puede buscar en el catálogo."""

    kind: ObjectKind
    name: str  # column → "tabla.columna"; enum_value → "tipo:valor"
    migration: str
    alive: bool = True


@dataclass
class MigrationStatus:
    migration: str
    expected: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def state(self) -> Literal["applied", "missing", "partial", "unverifiable"]:
        if not self.expected:
            return "unverifiable"
        if not self.missing:
            return "applied"
        return "missing" if len(self.missing) == len(self.expected) else "partial"


@dataclass(frozen=True)
class LiveSchema:
    """Lo que hay de verdad en la base (schema `public` + buckets de Storage)."""

    tables: frozenset[str]
    columns: frozenset[str]  # "tabla.columna"
    indexes: frozenset[str]
    types: frozenset[str]
    enum_values: frozenset[str]  # "tipo:valor"
    buckets: frozenset[str] | None  # None si no se pudo leer storage.buckets

    def has(self, obj: SchemaObject) -> bool | None:
        """True/False si existe; None si no se puede saber (buckets ilegibles)."""
        if obj.kind == "table":
            return obj.name in self.tables
        if obj.kind == "column":
            return obj.name in self.columns
        if obj.kind == "index":
            return obj.name in self.indexes
        if obj.kind == "type":
            return obj.name in self.types
        if obj.kind == "enum_value":
            return obj.name in self.enum_values
        if self.buckets is None:
            return None
        return obj.name in self.buckets


# ─── Parser ───────────────────────────────────────────────────────────────────


def _strip_comments_and_bodies(sql: str) -> str:
    """Quita comentarios y cuerpos `$$ … $$` (funciones/DO), respetando strings '…'."""
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'" and j + 1 < n and sql[j + 1] == "'":
                    j += 2
                    continue
                if sql[j] == "'":
                    break
                j += 1
            out.append(sql[i : j + 1])
            i = j + 1
        elif sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j == -1 else j
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = n if j == -1 else j + 2
        elif ch == "$":
            match = re.match(r"\$([A-Za-z_]*)\$", sql[i:])
            if match is None:
                out.append(ch)
                i += 1
                continue
            tag = match.group(0)
            j = sql.find(tag, i + len(tag))
            out.append("''")
            i = n if j == -1 else j + len(tag)
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _split_top_level(text: str, sep: str) -> list[str]:
    """Parte por `sep` fuera de paréntesis y strings."""
    parts: list[str] = []
    depth = 0
    in_string = False
    current: list[str] = []
    for ch in text:
        if ch == "'":
            in_string = not in_string
        elif not in_string and ch == "(":
            depth += 1
        elif not in_string and ch == ")":
            depth -= 1
        if ch == sep and depth == 0 and not in_string:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


def split_statements(sql: str) -> list[str]:
    """Sentencias normalizadas (sin comentarios ni cuerpos de función, espacios simples)."""
    cleaned = _strip_comments_and_bodies(sql)
    return [re.sub(r"\s+", " ", stmt) for stmt in _split_top_level(cleaned, ";")]


class _Replay:
    """Reproduce el DDL de las migraciones en orden."""

    def __init__(self) -> None:
        self.objects: list[SchemaObject] = []
        self._index_table: dict[str, str] = {}

    def _alive(self, kind: ObjectKind, name: str) -> list[SchemaObject]:
        return [o for o in self.objects if o.alive and o.kind == kind and o.name == name]

    def _add(self, kind: ObjectKind, name: str, migration: str) -> None:
        self.objects.append(SchemaObject(kind=kind, name=name, migration=migration))

    def _kill(self, kind: ObjectKind, name: str) -> None:
        for obj in self._alive(kind, name):
            obj.alive = False

    def _drop_table(self, table: str) -> None:
        self._kill("table", table)
        for obj in self.objects:
            if obj.alive and obj.kind == "column" and obj.name.startswith(f"{table}."):
                obj.alive = False
        for index, owner in list(self._index_table.items()):
            if owner == table:
                self._kill("index", index)

    def _rename_table(self, old: str, new: str) -> None:
        for obj in self._alive("table", old):
            obj.name = new
        for obj in self.objects:
            if obj.alive and obj.kind == "column" and obj.name.startswith(f"{old}."):
                obj.name = f"{new}.{obj.name.split('.', 1)[1]}"
        for index, owner in self._index_table.items():
            if owner == old:
                self._index_table[index] = new

    def apply(self, stmt: str, migration: str) -> None:  # un caso por sentencia
        low = stmt.lower()

        create_table = rf"create (?:unlogged )?table (?:if not exists )?{_IDENT}"
        if match := re.match(create_table, stmt, re.I):
            self._add("table", match.group(1).lower(), migration)
            return

        if match := re.match(
            rf"create (?:unique )?index (?:concurrently )?(?:if not exists )?{_IDENT} on "
            rf"(?:only )?{_IDENT}",
            stmt,
            re.I,
        ):
            index, table = match.group(1).lower(), match.group(2).lower()
            if index != "on":
                self._add("index", index, migration)
                self._index_table[index] = table
            return

        if match := re.match(r"drop index (?:concurrently )?(?:if exists )?(.+)", stmt, re.I):
            for raw in _split_top_level(match.group(1), ","):
                name = re.match(_IDENT, raw.split(" ")[0])
                if name:
                    self._kill("index", name.group(1).lower())
            return

        if match := re.match(r"drop table (?:if exists )?(.+)", stmt, re.I):
            for raw in _split_top_level(match.group(1), ","):
                name = re.match(_IDENT, raw.split(" ")[0])
                if name:
                    self._drop_table(name.group(1).lower())
            return

        if match := re.match(
            rf"alter index (?:if exists )?{_IDENT} rename to {_IDENT}", stmt, re.I
        ):
            old, new = match.group(1).lower(), match.group(2).lower()
            for obj in self._alive("index", old):
                obj.name = new
            if old in self._index_table:
                self._index_table[new] = self._index_table.pop(old)
            return

        if match := re.match(rf"create type {_IDENT} as enum ?\((.*)\)", stmt, re.I):
            type_name = match.group(1).lower()
            self._add("type", type_name, migration)
            for value in re.findall(r"'((?:[^']|'')*)'", match.group(2)):
                self._add("enum_value", f"{type_name}:{value}", migration)
            return

        if match := re.match(
            rf"alter type {_IDENT} add value (?:if not exists )?'((?:[^']|'')*)'", stmt, re.I
        ):
            self._add("enum_value", f"{match.group(1).lower()}:{match.group(2)}", migration)
            return

        if match := re.match(
            rf"alter type {_IDENT} rename value '((?:[^']|'')*)' to '((?:[^']|'')*)'", stmt, re.I
        ):
            type_name = match.group(1).lower()
            for obj in self._alive("enum_value", f"{type_name}:{match.group(2)}"):
                obj.name = f"{type_name}:{match.group(3)}"
            return

        if match := re.match(rf"drop type (?:if exists )?{_IDENT}", stmt, re.I):
            type_name = match.group(1).lower()
            self._kill("type", type_name)
            for obj in self.objects:
                if obj.alive and obj.kind == "enum_value" and obj.name.startswith(f"{type_name}:"):
                    obj.alive = False
            return

        if low.startswith("insert into storage.buckets"):
            values = re.search(r"\bvalues ?\( ?'([^']+)'", stmt, re.I)
            if values:
                self._add("bucket", values.group(1), migration)
            return

        if match := re.match(rf"alter table (?:if exists )?(?:only )?{_IDENT} (.*)", stmt, re.I):
            self._alter_table(match.group(1).lower(), match.group(2), migration)

    def _alter_table(self, table: str, actions: str, migration: str) -> None:
        if match := re.match(rf"rename to {_IDENT}$", actions, re.I):
            self._rename_table(table, match.group(1).lower())
            return
        if match := re.match(rf"rename (?:column )?{_IDENT} to {_IDENT}$", actions, re.I):
            old, new = match.group(1).lower(), match.group(2).lower()
            for obj in self._alive("column", f"{table}.{old}"):
                obj.name = f"{table}.{new}"
            return
        for action in _split_top_level(actions, ","):
            if match := re.match(rf"add (?:column )?(?:if not exists )?{_IDENT}", action, re.I):
                column = match.group(1).lower()
                if column not in _TABLE_CONSTRAINT_WORDS:
                    self._add("column", f"{table}.{column}", migration)
            elif match := re.match(rf"drop column (?:if exists )?{_IDENT}", action, re.I):
                self._kill("column", f"{table}.{match.group(1).lower()}")


def expected_objects(migrations_dir: Path = MIGRATIONS_DIR) -> tuple[list[str], list[SchemaObject]]:
    """(nombres de migración en orden, objetos que deberían existir hoy)."""
    files = sorted(migrations_dir.glob("*.sql"))
    replay = _Replay()
    for path in files:
        for stmt in split_statements(path.read_text(encoding="utf-8")):
            replay.apply(stmt, path.name)
    return [p.name for p in files], [o for o in replay.objects if o.alive]


def migration_statuses(
    migrations: list[str], objects: list[SchemaObject], live: LiveSchema
) -> list[MigrationStatus]:
    by_name = {name: MigrationStatus(migration=name) for name in migrations}
    for obj in objects:
        present = live.has(obj)
        if present is None:
            continue
        label = f"{obj.kind} {obj.name}"
        status = by_name[obj.migration]
        status.expected.append(label)
        if not present:
            status.missing.append(label)
    return [by_name[name] for name in migrations]


async def read_live_schema(conn: asyncpg.Connection) -> LiveSchema:
    """Lee el catálogo. `storage.buckets` puede no existir (Postgres sin Supabase)."""
    tables = await conn.fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    )
    columns = await conn.fetch(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'public'"
    )
    indexes = await conn.fetch("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
    enums = await conn.fetch(
        "SELECT t.typname, e.enumlabel FROM pg_type t "
        "JOIN pg_namespace n ON n.oid = t.typnamespace "
        "LEFT JOIN pg_enum e ON e.enumtypid = t.oid "
        "WHERE n.nspname = 'public' AND t.typtype IN ('e', 'c', 'd')"
    )
    has_storage = await conn.fetchval("SELECT to_regclass('storage.buckets') IS NOT NULL")
    buckets: frozenset[str] | None = None
    if has_storage:
        buckets = frozenset(r["id"] for r in await conn.fetch("SELECT id FROM storage.buckets"))
    return LiveSchema(
        tables=frozenset(r["table_name"] for r in tables),
        columns=frozenset(f"{r['table_name']}.{r['column_name']}" for r in columns),
        indexes=frozenset(r["indexname"] for r in indexes),
        types=frozenset(r["typname"] for r in enums),
        enum_values=frozenset(
            f"{r['typname']}:{r['enumlabel']}" for r in enums if r["enumlabel"] is not None
        ),
        buckets=buckets,
    )
