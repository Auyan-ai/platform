# Agente escala

Cuando el comprador pide una persona o plantea una queja grave, el grafo decide `escalate`, crea una escalación con razón explícita y no inventa una respuesta.

## Sub-features

- `escalate-human` petición explícita de hablar con una persona.
- `escalate-reason` la escalación guarda un motivo legible en `escalations.reason`.

## How to get to it (user POV)

- El comprador escribe que quiere hablar con alguien / reporta un problema grave (p. ej. doble cobro) por cualquier canal; aquí vía `POST /webhooks/inbound`.

## Driving it with scripts/ (curl firmado + psql de solo lectura)

Preconditions:

- Las de `agent-respond.md`.

- **Provocar el escalado.** `.claude/skills/verify/scripts/inbound.sh marea-studio "Necesito hablar con una persona ahora mismo. Me habéis cobrado dos veces y nadie me responde."`. HTTP 200, `"decision": "escalate"`, `escalation_id` no nulo, `escalation_reason` con causa (`customer_requesting_human_agent + serious_complaint…`).
- **Confirmar la escalación.** `.claude/skills/verify/scripts/dump.sh <conversation_id>`: sección `escalations` con una fila abierta y su `reason`; en `agent_reasoning_events` aparece la decisión de escalar.
- **Qué NO ocurre aquí.** Con `channel=chat` no hay helpdesk: no se crea ticket ni nota interna. Eso solo se prueba con un helpdesk real (Zendesk/Chatwoot/Gorgias de staging), fuera de este skill.

## Gotchas

- La conversación queda con una escalación abierta en staging; aparece en la cola de Escalaciones del dashboard de Marea hasta que alguien la resuelva (no la resuelvas sin avisar a Kenny).
- El texto exacto del motivo varía por corrida: asierta que existe y que menciona la causa, no la cadena completa.
