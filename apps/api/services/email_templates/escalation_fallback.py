"""Template para escalación fallback: cuando el tenant no tiene helpdesk configurado.

Se usa para notificar al equipo CX del cliente que hay un ticket que necesita
atención humana, junto con el contexto del agente.
"""

from __future__ import annotations


def render(
    *,
    tenant_name: str,
    conversation_id: str,
    reason: str,
    customer_email: str | None = None,
    agent_summary: str | None = None,
) -> tuple[str, str, str]:
    """Genera (subject, text_body, html_body) para escalación fallback.

    Args:
        tenant_name: nombre del tenant (para personalizar el saludo).
        conversation_id: UUID de la conversación en Auyan.
        reason: motivo del escalado, tal como lo registró el agente.
        customer_email: email del cliente final (opcional, para contexto).
        agent_summary: resumen del agente sobre la conversación (opcional).

    Returns:
        Tupla (subject, text_body, html_body).
    """
    subject = f"[Auyan] Escalación pendiente — {tenant_name}"

    customer_line = f"Cliente: {customer_email}" if customer_email else ""
    summary_section = f"\nResumen del agente:\n{agent_summary}" if agent_summary else ""

    text_body = f"""\
Hola, equipo de {tenant_name}.

El agente de Auyan ha escalado una conversación que requiere atención humana.

Conversación ID: {conversation_id}
{customer_line}
Motivo del escalado: {reason}{summary_section}

Por favor, revisa la conversación en tu panel de soporte y continúa la atención al cliente.

—
Auyan · Managed AI Service
Este es un mensaje automático. No respondas a este email.
"""

    html_body = f"""\
<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><title>Escalación Auyan</title></head>
<body style="font-family:sans-serif;color:#1a1a1a;max-width:600px;margin:0 auto;padding:24px">
  <h2 style="color:#7c3aed">Auyan — Escalación pendiente</h2>
  <p>Hola, equipo de <strong>{tenant_name}</strong>.</p>
  <p>El agente de Auyan ha escalado una conversación que requiere atención humana.</p>
  <table style="border-collapse:collapse;width:100%;margin:16px 0">
    <tr>
      <td style="padding:8px;background:#f5f3ff;font-weight:bold;width:160px">Conversación ID</td>
      <td style="padding:8px;background:#faf9ff;font-family:monospace">{conversation_id}</td>
    </tr>
    {"<tr><td style='padding:8px;background:#f5f3ff;font-weight:bold'>Cliente</td><td style='padding:8px;background:#faf9ff'>" + customer_email + "</td></tr>" if customer_email else ""}
    <tr>
      <td style="padding:8px;background:#f5f3ff;font-weight:bold">Motivo</td>
      <td style="padding:8px;background:#faf9ff">{reason}</td>
    </tr>
  </table>
  {"<h3>Resumen del agente</h3><pre style='background:#f5f3ff;padding:12px;border-radius:4px;white-space:pre-wrap'>" + agent_summary + "</pre>" if agent_summary else ""}
  <p>Por favor, revisa la conversación en tu panel de soporte y continúa la atención.</p>
  <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0">
  <p style="font-size:12px;color:#6b7280">Auyan · Managed AI Service<br>
  Este es un mensaje automático. No respondas a este email.</p>
</body>
</html>
"""

    return subject, text_body, html_body
