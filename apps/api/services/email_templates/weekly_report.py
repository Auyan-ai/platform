"""Template para reporte semanal enviado al cliente."""

from __future__ import annotations

from html import escape
from typing import Any


def _metric(metrics: dict[str, Any], *path: str, default: Any = 0) -> Any:
    value: Any = metrics
    for key in path:
        if not isinstance(value, dict):
            return default
        value = value.get(key, default)
    return value


def render(
    *,
    subject: str,
    week_start: str,
    week_end: str,
    metrics: dict[str, Any],
    narrative: str,
) -> tuple[str, str, str]:
    conversations = _metric(metrics, "volume", "conversations")
    messages = _metric(metrics, "volume", "messages")
    resolution_rate = metrics.get("resolution_rate", 0)
    escalation_rate = metrics.get("escalation_rate", 0)
    cost_usd = _metric(metrics, "cost", "usd", default=0)

    text_body = f"""\
{subject}

Semana: {week_start} a {week_end}

Conversaciones: {conversations}
Mensajes: {messages}
Resolution rate: {resolution_rate}%
Escalation rate: {escalation_rate}%
Coste LLM estimado: ${float(cost_usd):.4f}

{narrative}

--
Auyan
"""

    safe_narrative = "<br>".join(escape(narrative).splitlines())
    html_body = f"""\
<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><title>{escape(subject)}</title></head>
<body style="font-family:sans-serif;color:#1a1a1a;max-width:680px;margin:0 auto;padding:24px">
  <h2 style="margin:0 0 8px">{escape(subject)}</h2>
  <p style="margin:0 0 24px;color:#64748b">Semana: {escape(week_start)} a {escape(week_end)}</p>
  <table style="border-collapse:collapse;width:100%;margin:16px 0">
    <tr><td style="padding:10px;background:#f8fafc;font-weight:bold">Conversaciones</td><td style="padding:10px;background:#f8fafc">{conversations}</td></tr>
    <tr><td style="padding:10px;background:#fff;font-weight:bold">Mensajes</td><td style="padding:10px;background:#fff">{messages}</td></tr>
    <tr><td style="padding:10px;background:#f8fafc;font-weight:bold">Resolution rate</td><td style="padding:10px;background:#f8fafc">{resolution_rate}%</td></tr>
    <tr><td style="padding:10px;background:#fff;font-weight:bold">Escalation rate</td><td style="padding:10px;background:#fff">{escalation_rate}%</td></tr>
    <tr><td style="padding:10px;background:#f8fafc;font-weight:bold">Coste LLM estimado</td><td style="padding:10px;background:#f8fafc">${float(cost_usd):.4f}</td></tr>
  </table>
  <div style="line-height:1.6">{safe_narrative}</div>
  <hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0">
  <p style="font-size:12px;color:#64748b">Auyan</p>
</body>
</html>
"""

    return subject, text_body, html_body
