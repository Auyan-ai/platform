"""Baterías de preguntas para "Probar agente": carga del YAML, ejecución y tabla.

Cada pregunta abre un chat nuevo salvo que el YAML marque `same_chat: true`, que la manda
al chat de la pregunta anterior (seguimientos). El envío real va inyectado, así que la
lógica se prueba sin grafo ni base de datos.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml


@dataclass(frozen=True)
class BatteryQuestion:
    id: int
    ask: str
    expected: str
    chatbase: str | None = None
    same_chat: bool = False


@dataclass(frozen=True)
class Battery:
    name: str
    description: str
    questions: list[BatteryQuestion]


@dataclass
class BatteryRow:
    question: BatteryQuestion
    chat_id: UUID | None = None
    decision: str = ""
    reply: str = ""
    escalation_reason: str | None = None
    trace_id: str | None = None
    cost_cents: float = 0.0
    error: str | None = None
    skills: list[str] = field(default_factory=list)


def load_battery(path: Path) -> Battery:
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("questions"), list):
        raise ValueError(f"{path}: se esperaba un mapa con la lista `questions`")
    questions: list[BatteryQuestion] = []
    seen: set[int] = set()
    for i, item in enumerate(raw["questions"]):
        if not isinstance(item, dict) or not item.get("ask") or not item.get("expected"):
            raise ValueError(f"{path}: la pregunta #{i + 1} necesita `ask` y `expected`")
        qid = int(item.get("id", i + 1))
        if qid in seen:
            raise ValueError(f"{path}: id de pregunta repetido: {qid}")
        seen.add(qid)
        if item.get("same_chat") and not questions:
            raise ValueError(f"{path}: la pregunta {qid} no puede seguir a ninguna")
        questions.append(
            BatteryQuestion(
                id=qid,
                ask=str(item["ask"]),
                expected=str(item["expected"]),
                chatbase=str(item["chatbase"]) if item.get("chatbase") else None,
                same_chat=bool(item.get("same_chat", False)),
            )
        )
    if not questions:
        raise ValueError(f"{path}: la batería no tiene preguntas")
    return Battery(
        name=str(raw.get("name", path.stem)),
        description=str(raw.get("description", "")).strip(),
        questions=questions,
    )


NewChat = Callable[[], Awaitable[UUID]]
SendMessage = Callable[[UUID, str], Awaitable[Any]]


async def run_battery(
    battery: Battery,
    *,
    new_chat: NewChat,
    send: SendMessage,
    ensure_budget: Callable[[], Awaitable[None]],
) -> list[BatteryRow]:
    """Corre las preguntas en orden. `ensure_budget` se llama antes de cada turno y lanza si
    el tope diario se alcanzó; lo ya respondido se conserva en la excepción vía `rows`."""
    rows: list[BatteryRow] = []
    chat_id: UUID | None = None
    for q in battery.questions:
        await ensure_budget()
        if chat_id is None or not q.same_chat:
            chat_id = await new_chat()
        turn = await send(chat_id, q.ask)
        rows.append(
            BatteryRow(
                question=q,
                chat_id=chat_id,
                decision=turn.decision,
                reply=turn.response_text,
                escalation_reason=turn.escalation_reason,
                trace_id=turn.trace_id,
                cost_cents=turn.cost_cents,
                error=turn.error,
                skills=list(turn.skills),
            )
        )
    return rows


def _cell(text: str, width: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[: width - 1] + "…"


def format_table(rows: list[BatteryRow], *, ask_width: int = 40, reply_width: int = 90) -> str:
    header = f"{'#':>2}  {'pregunta':<{ask_width}}  {'decisión':<9}  respuesta"
    lines = [header, "-" * len(header)]
    for r in rows:
        decision = r.decision + ("*" if r.escalation_reason else "")
        reply = r.reply or (f"[{r.error}]" if r.error else "")
        lines.append(
            f"{r.question.id:>2}  {_cell(r.question.ask, ask_width):<{ask_width}}  "
            f"{decision:<9}  {_cell(reply, reply_width)}"
        )
    escalated = [r for r in rows if r.escalation_reason]
    if escalated:
        lines.append("")
        lines.append("* Razones de escalado:")
        for r in escalated:
            lines.append(f"  #{r.question.id}: {_cell(r.escalation_reason or '', 160)}")
    total = sum(r.cost_cents for r in rows)
    lines.append("")
    lines.append(f"Coste de la batería: ${total / 100:.4f} ({len(rows)} preguntas)")
    return "\n".join(lines)


def list_questions(battery: Battery) -> str:
    lines = [f"Batería {battery.name}: {len(battery.questions)} preguntas"]
    for q in battery.questions:
        follow = " (mismo chat)" if q.same_chat else ""
        lines.append(f"{q.id:>2}. {q.ask}{follow}\n    esperado: {q.expected}")
    return "\n".join(lines)
