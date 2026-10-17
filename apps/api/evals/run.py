"""CLI de evals. `--static` corre la capa determinista (sin LLM, sin red) y es la que bloquea el CI.

    cd apps/api && PYTHONPATH=../.. python -m apps.api.evals.run --static

Corre cada fixture de `evals/fixtures/<slug>/` contra el AOP canónico del mismo slug
(`aops/canonical.py`, la fuente de verdad en código) compilado con una configuración de
tenant mínima. Sale con código 1 si falla cualquier fixture (aquí no vale el 80% del gate
de promoción), si un fixture usa un tipo de aserción no declarado estático, si hay
fixtures de un slug sin AOP canónico o un AOP canónico sin fixtures. Cualquier intento de
abrir un socket durante la corrida lanza `NetworkBlockedError`: nunca se salta en silencio.
"""

from __future__ import annotations

import argparse
import socket
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from apps.api.aops.canonical import CANONICAL_AOPS, CANONICAL_WORKSPACE, _build_raw_source
from apps.api.db.models import AopWithContent
from apps.api.evals.harness import (
    FIXTURES_DIR,
    FixtureResult,
    _default_tenant_config,
    load_fixtures,
    non_static_kinds,
    run_fixture,
)

_STATIC_TENANT_ID = UUID("00000000-0000-0000-0000-00000000e7a1")


class NetworkBlockedError(RuntimeError):
    """Se intentó usar la red en modo estático."""


@contextmanager
def network_blocked() -> Iterator[None]:
    def _blocked(*_args: Any, **_kwargs: Any) -> Any:
        raise NetworkBlockedError(
            "Las evals estáticas no pueden usar la red (¿una aserción llama al LLM?)"
        )

    methods = ("connect", "connect_ex")
    funcs = ("getaddrinfo", "create_connection")
    saved_methods = {n: getattr(socket.socket, n) for n in methods}
    saved_funcs = {n: getattr(socket, n) for n in funcs}
    try:
        for n in methods:
            setattr(socket.socket, n, _blocked)
        for n in funcs:
            setattr(socket, n, _blocked)
        yield
    finally:
        for n, f in saved_methods.items():
            setattr(socket.socket, n, f)
        for n, g in saved_funcs.items():
            setattr(socket, n, g)


@dataclass
class StaticRunReport:
    results: list[tuple[str, FixtureResult]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def failed(self) -> list[tuple[str, FixtureResult]]:
        return [(slug, r) for slug, r in self.results if not r.passed]

    @property
    def ok(self) -> bool:
        return not self.errors and not self.failed


def _canonical_as_aop(entry: dict[str, Any]) -> AopWithContent:
    return AopWithContent(
        id=UUID(int=0),
        tenant_id=_STATIC_TENANT_ID,
        slug=entry["slug"],
        workspace=CANONICAL_WORKSPACE,
        current_version=1,
        yaml_frontmatter=entry["frontmatter"],
        body_markdown=entry["body"],
        raw_source=_build_raw_source(entry["frontmatter"], entry["body"]),
    )


def run_static() -> StaticRunReport:
    report = StaticRunReport()
    canonical = {e["slug"]: e for e in CANONICAL_AOPS}
    fixture_slugs = sorted(p.name for p in FIXTURES_DIR.iterdir() if p.is_dir())

    for slug in fixture_slugs:
        if slug not in canonical:
            report.errors.append(f"fixtures/{slug}/ no tiene AOP canónico con ese slug")
    for slug in canonical:
        if slug not in fixture_slugs:
            report.errors.append(f"el AOP canónico '{slug}' no tiene fixtures")

    tenant_config = _default_tenant_config(_STATIC_TENANT_ID)
    with network_blocked():
        for slug in fixture_slugs:
            if slug not in canonical:
                continue
            aop = _canonical_as_aop(canonical[slug])
            for fixture in load_fixtures(slug):
                bad = non_static_kinds(fixture)
                if bad:
                    report.errors.append(
                        f"{slug}/{fixture.name}: tipos de aserción no estáticos {bad}"
                    )
                    continue
                report.results.append((slug, run_fixture(aop, tenant_config, fixture)))
    return report


def format_report(report: StaticRunReport) -> str:
    lines: list[str] = []
    for slug, r in report.results:
        lines.append(f"{'PASS' if r.passed else 'FAIL'} {slug}/{r.fixture_name}")
        if not r.passed:
            lines.extend(
                f"       - {a.kind}: {a.message}" for a in r.assertion_results if not a.passed
            )
    lines.extend(f"ERROR {e}" for e in report.errors)
    total = len(report.results)
    passed = total - len(report.failed)
    lines.append(
        f"evals estáticas: {passed}/{total} fixtures OK, {len(report.failed)} fallan, "
        f"{len(report.errors)} errores"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evals del agente")
    parser.add_argument(
        "--static",
        action="store_true",
        required=True,
        help="solo las evals deterministas (sin LLM ni red); exit 1 si alguna falla",
    )
    parser.parse_args(argv)
    report = run_static()
    print(format_report(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
