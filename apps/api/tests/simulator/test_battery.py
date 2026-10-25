"""Batería de preguntas: YAML de Thinking MU, ejecución con chats y tabla."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from apps.api.evals.battery import (
    format_table,
    list_questions,
    load_battery,
    run_battery,
)
from apps.api.scripts import run_battery as script

BATTERY = Path(__file__).resolve().parents[2] / "evals" / "batteries" / "thinkingmu.yaml"


def test_thinkingmu_battery_has_the_16_appendix_questions():
    battery = load_battery(BATTERY)

    assert [q.id for q in battery.questions] == list(range(1, 17))
    assert battery.questions[0].ask == "¿Cuánto cuesta el envío a Canarias?"
    assert battery.questions[0].expected == "19,90 €, gratis desde 140 €, 3-5 días hábiles"
    assert battery.questions[15].expected == "Igual que la 15"
    assert not any(q.same_chat for q in battery.questions)


def test_dry_run_lists_questions_without_touching_anything(capsys: pytest.CaptureFixture[str]):
    code = script.main(["--tenant", "thinkingmu-demo", "--file", str(BATTERY), "--dry-run"])

    out = capsys.readouterr().out
    assert code == 0
    assert "16 preguntas" in out
    assert "¿Puedo pagar con Klarna?" in out


def test_invalid_battery_is_rejected(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("questions:\n  - ask: hola\n")

    with pytest.raises(ValueError, match="necesita"):
        load_battery(bad)


async def test_follow_up_reuses_chat_and_others_open_new_ones(tmp_path: Path):
    f = tmp_path / "b.yaml"
    f.write_text(
        "questions:\n"
        "  - {id: 1, ask: uno, expected: a}\n"
        "  - {id: 2, ask: dos, expected: b, same_chat: true}\n"
        "  - {id: 3, ask: tres, expected: c}\n"
    )
    opened: list = []
    sent: list = []

    async def new_chat():
        opened.append(uuid4())
        return opened[-1]

    async def send(chat_id, text):
        sent.append((chat_id, text))
        return SimpleNamespace(
            decision="escalate" if text == "tres" else "respond",
            response_text=f"r-{text}",
            escalation_reason="sin dato" if text == "tres" else None,
            trace_id=None,
            cost_cents=1.5,
            error=None,
            skills=[],
        )

    async def budget():
        return None

    battery = load_battery(f)
    rows = await run_battery(battery, new_chat=new_chat, send=send, ensure_budget=budget)

    assert len(opened) == 2
    assert [c for c, _ in sent] == [opened[0], opened[0], opened[1]]
    table = format_table(rows)
    assert "escalate*" in table
    assert "#3: sin dato" in table
    assert "$0.0450" in table
    assert "(mismo chat)" in list_questions(battery)


async def test_cap_reached_runs_nothing():
    from apps.api.simulator.cost_guard import SimulationBudgetExceeded

    opened: list = []

    async def new_chat():
        opened.append(1)
        return uuid4()

    async def send(chat_id, text):
        raise AssertionError("no debe correr con el tope alcanzado")

    async def budget():
        raise SimulationBudgetExceeded("tope", retry_after=60)

    with pytest.raises(SimulationBudgetExceeded):
        await run_battery(load_battery(BATTERY), new_chat=new_chat, send=send, ensure_budget=budget)
    assert opened == []
