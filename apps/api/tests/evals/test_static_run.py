"""Tests de la capa estática de evals (`python -m apps.api.evals.run --static`, issue #326)."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
import yaml
from apps.api.evals import harness, run
from apps.api.evals.harness import FIXTURES_DIR, STATIC_ASSERTION_KINDS, load_fixtures


def _all_fixture_kinds() -> set[str]:
    return {
        a.kind
        for d in FIXTURES_DIR.iterdir()
        if d.is_dir()
        for f in load_fixtures(d.name)
        for a in f.assertions
    }


def test_every_fixture_kind_is_declared_static() -> None:
    # Si alguien añade una fixture con un tipo nuevo (p. ej. judge con LLM), esto obliga
    # a decidir a propósito si es estática; el tipo no se cuela por accidente.
    assert _all_fixture_kinds() <= STATIC_ASSERTION_KINDS


def test_every_static_kind_is_implemented_by_the_checker() -> None:
    for kind in STATIC_ASSERTION_KINDS:
        result = harness._check_assertion(kind, None, None, None, "sin compilar")  # type: ignore[arg-type]
        assert "desconocido" not in result.message, kind


def test_every_fixture_file_is_loaded() -> None:
    on_disk = sum(1 for _ in FIXTURES_DIR.glob("*/*.yaml"))
    loaded = sum(len(load_fixtures(d.name)) for d in FIXTURES_DIR.iterdir() if d.is_dir())
    assert loaded == on_disk


def test_static_run_passes_on_the_repo_and_returns_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert run.main(["--static"]) == 0
    assert "0 fallan, 0 errores" in capsys.readouterr().out


def _write_fixture(root: Path, slug: str, name: str, assertions: list[dict]) -> None:
    d = root / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.yaml").write_text(
        yaml.safe_dump({"name": name, "assertions": assertions}), encoding="utf-8"
    )


def test_failing_fixture_makes_the_run_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for slug in FIXTURES_DIR.iterdir():
        if slug.is_dir():
            _write_fixture(tmp_path, slug.name, "ok", [{"kind": "compile_ok"}])
    _write_fixture(
        tmp_path,
        "refunds",
        "roto",
        [{"kind": "prompt_contains", "expected": ["frase que no existe jamas"]}],
    )
    monkeypatch.setattr(run, "FIXTURES_DIR", tmp_path)
    monkeypatch.setattr(harness, "FIXTURES_DIR", tmp_path)

    assert run.main(["--static"]) == 1
    out = capsys.readouterr().out
    assert "FAIL refunds/roto" in out
    assert "frase que no existe jamas" in out


def test_non_static_kind_fails_loud_instead_of_being_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for slug in FIXTURES_DIR.iterdir():
        if slug.is_dir():
            _write_fixture(tmp_path, slug.name, "ok", [{"kind": "compile_ok"}])
    _write_fixture(tmp_path, "default", "con_llm", [{"kind": "llm_judge", "expected": "x"}])
    monkeypatch.setattr(run, "FIXTURES_DIR", tmp_path)
    monkeypatch.setattr(harness, "FIXTURES_DIR", tmp_path)

    assert run.main(["--static"]) == 1
    assert (
        "default/con_llm: tipos de aserción no estáticos ['llm_judge']" in capsys.readouterr().out
    )


def test_fixture_dir_without_canonical_aop_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for slug in FIXTURES_DIR.iterdir():
        if slug.is_dir():
            _write_fixture(tmp_path, slug.name, "ok", [{"kind": "compile_ok"}])
    _write_fixture(tmp_path, "huerfano", "ok", [{"kind": "compile_ok"}])
    monkeypatch.setattr(run, "FIXTURES_DIR", tmp_path)
    monkeypatch.setattr(harness, "FIXTURES_DIR", tmp_path)

    assert run.main(["--static"]) == 1
    assert "fixtures/huerfano/ no tiene AOP canónico" in capsys.readouterr().out


def test_network_is_blocked_during_static_run() -> None:
    with run.network_blocked():
        with pytest.raises(run.NetworkBlockedError):
            socket.create_connection(("api.anthropic.com", 443))
        with pytest.raises(run.NetworkBlockedError):
            socket.socket().connect(("127.0.0.1", 9))


def test_network_is_restored_after_the_block() -> None:
    before = socket.create_connection
    with run.network_blocked():
        pass
    assert socket.create_connection is before
