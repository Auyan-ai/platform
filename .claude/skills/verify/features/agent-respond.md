# Agente responde

Un mensaje del comprador entra por el webhook firmado, el grafo (select_aop → ReAct → skills/RAG) decide `respond` y devuelve una respuesta fundada en la base de conocimiento o en una skill de Shopify, dejando mensaje, razonamiento y trace.

## Sub-features

- `respond-kb` pregunta de política contestada con la KB / `shopify.get_shop_policies`.
- `respond-multiturn` segundo mensaje en la misma conversación.
- `respond-trace` la respuesta trae `trace_id` y la conversación queda cerrada como `resolved`.

## How to get to it (user POV)

- El comprador escribe en el chat del cliente → helpdesk → webhook a Auyan (aquí, el equivalente sintético): `POST /webhooks/inbound` con `channel=chat`.

## Driving it with scripts/ (curl firmado + psql de solo lectura)

Preconditions:

- `doctor.sh` sin `FAIL`; API local arriba.
- Marea Studio activo (`select status from tenants where slug='marea-studio'` = `active`).

- **Preguntar política.** `.claude/skills/verify/scripts/inbound.sh marea-studio "Hola, ¿cuál es vuestra política de devoluciones?"`. HTTP 200, `"ok": true`, `"decision": "respond"`, `response_text` con plazo de 30 días, `escalation_id: null`, `trace_id` presente. Tarda ~20 s (LLM real).
- **Confirmar en Supabase.** `.claude/skills/verify/scripts/dump.sh <conversation_id>`. Hay un mensaje `customer/inbound` y un `agent_ai/outbound`; `agent_reasoning_events` muestra `Load context` → `shopify.get_shop_policies` (tool_call + tool_result) → `Decision: respond`; la conversación pasa a `resolved`; 0 escalaciones.
- **Multi-turno.** `.claude/skills/verify/scripts/inbound.sh marea-studio "¿y cuánto tarda el reembolso?" <conversation_id>`. Misma `conversation_id` en la respuesta y 4 mensajes en `dump.sh`.
- **Trace.** `.claude/skills/verify/scripts/trace.sh <trace_id>`: `http=200`, run `agent_conversation`, `status: success`, `error: None`.

## Gotchas

- Marca/idioma: el agente contesta con el tono del tenant; no asertes el texto exacto, asierta `decision`, la presencia de datos de la política y los eventos de razonamiento.
- Si Supabase está pausado, `doctor.sh` lo dice antes; reanudarlo toma minutos.
- Cada corrida cuesta LLM real y crea un cliente nuevo (`verify-<timestamp>@example.com`).
- `/webhooks/inbound` devuelve la respuesta en el body y **no** entrega al helpdesk; la entrega por Zendesk/Chatwoot/WhatsApp no se prueba aquí.
