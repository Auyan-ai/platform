# ADR 0010 — WhatsApp vía Zernio como canal de mensajería, desacoplado del helpdesk, con handoff al helpdesk del cliente

**Estado:** Propuesta (pasa a Aceptada cuando el spike C0 confirme firma, precios y add-ons, y se mergee la implementación)
**Fecha:** 2026-09-30 (sesión 79, planificación del Sprint 2)

## Contexto

En España la mayoría de marcas atiende por WhatsApp, y es requisito del piloto. Hasta ahora
todos los canales de Auyan son **helpdesks** (Zendesk, Gorgias, Chatwoot), y el código asume
que `conversation.channel` **es** el helpdesk. La misma integración recibe el mensaje, entrega la
respuesta, escala (nota interna + asignación) y cierra el ticket. Cuatro puntos dependen de esa
igualdad:

- entrega del turno: `services/inbound_worker._deliver_outcome` → `load_helpdesk_client`;
- aprobaciones L3: `helpdesk_delivery.deliver_message_to_helpdesk` y
  `approval_resolution.reply_delivered`. Esta última da por **entregado** cualquier canal sin
  adapter de helpdesk, así que en WhatsApp mentiría;
- escalado: `helpdesk_escalation.push_escalation_to_helpdesk`;
- cierre: `helpdesk_closure.close_external_helpdesk_ticket`.

WhatsApp rompe esa igualdad. La conversación vive en WhatsApp, pero el equipo CX del cliente
trabaja en su helpdesk, y la regla del proyecto es que los escalados van al helpdesk del cliente.

Restricciones de WhatsApp/Meta que condicionan el diseño:

- **Ventana de 24 h** desde el último mensaje del comprador. Fuera de ella solo se pueden mandar
  **plantillas aprobadas** por Meta. Intercom, Zendesk y Gorgias hacen lo mismo según su
  documentación oficial: bloquean el texto libre, el agente manda una plantilla y, cuando el
  comprador contesta, se abre una ventana nueva.
- **Identidad.** Desde abril de 2026 Meta despliega el *business-scoped user id* (BSUID). Un
  usuario con nombre de usuario de WhatsApp puede escribir **sin exponer su teléfono**. El BSUID
  es el ancla recomendada y el teléfono pasa a ser opcional.
- Límite de ~10 mensajes/min por destinatario (error `131056`).
- Los adjuntos (notas de voz, fotos) hay que descargarlos al llegar, porque Meta los borra.
- **Coexistence:** el número puede seguir usándose desde la app WhatsApp Business del móvil de
  la marca a la vez que la Cloud API.
- **Un chat de WhatsApp no termina nunca.** No hay "ticket nuevo por tema" como en un helpdesk.

Zernio (API unificada de mensajería) cubre lo que necesitamos. Lo verificamos en su OpenAPI a
través del SDK oficial `zernio-dev/zernio-php`, generado de la spec:

- Webhooks con HMAC-SHA256 en `X-Zernio-Signature` y un id de evento estable
  (`X-Zernio-Event-Id`), idéntico en reintentos y redeliveries, que sirve de clave de dedupe.
- Eventos: `message.received`, `message.sent` (con `source`: `cloud_api` /
  `whatsapp_business_app` / `meta_business_agent`, y con `sent_via`), `message.failed`,
  `message.delivered` y `conversation.control_changed`.
- Envío con `POST /v1/inbox/conversations/{id}/messages`, que acepta `Idempotency-Key` y
  `template`.
- `profiles`, con una cuenta de WhatsApp por profile.
- **API keys limitadas a profiles** (`scope=profiles`).
- Webhooks filtrables por `profileIds`/`accountIds`.
- **Embedded Signup hospedado** (`signup=hosted`, en coexistence por defecto).
- Sandbox de WhatsApp compartido para desarrollo.

El detalle exacto de la firma (qué se firma y en qué codificación) no aparece en la spec y se
verifica en C0.

## Decisión

**WhatsApp entra como canal de mensajería vía Zernio, desacoplado del helpdesk. El canal entrega
y el helpdesk del cliente recibe los handoffs a través de una interfaz común.**

1. **Proveedor de canal.** La integración es `tenant_integrations(kind='channel',
   provider='zernio')` y las conversaciones llevan `channel='whatsapp'` (el enum `channel_type`
   ya tiene ese valor, así que no hace falta migración). Auyan tiene **una cuenta de Zernio**
   con **un profile por tenant**. Cada tenant tiene una **API key limitada a su profile** y un
   secreto de webhook propio, los dos cifrados en `tenant_integrations` como el resto de
   credenciales. La key maestra solo la usan los scripts de operación y nunca entra en el
   runtime. El número y la WABA son **del cliente** (Embedded Signup con su Meta Business):
   en el offboarding se desconecta y el cliente conserva su número.
2. **Canal y helpdesk desacoplados.** Un único resolutor traduce el canal de la conversación a
   la integración que entrega (`zendesk`/`gorgias`/`chatwoot` → `helpdesk/<provider>`;
   `whatsapp` → `channel/zernio`). La entrega del turno, las aprobaciones, el escalado y el
   cierre pasan por él. Un canal con ruta de entrega nunca se da por entregado sin confirmación.
3. **Handoff modular al helpdesk del cliente.** Escalar en un canal de mensajería abre un ticket
   en el **helpdesk primario del tenant** (`is_primary_for_kind`) a través de la interfaz
   `HandoffTarget`, que tiene cuatro operaciones: abrir el ticket con transcripción y motivo,
   añadir un mensaje del comprador, reconocer una respuesta pública del agente humano y
   reconocer el cierre del ticket. **Zendesk es la primera implementación.** Gorgias y
   Chatwoot implementan la misma interfaz cuando un cliente lo pida. El estado vive en
   `conversation_handoffs`. Mientras el handoff está activo:
   - **el agente IA no corre**: cada mensaje del comprador se reenvía al ticket;
   - la respuesta pública del agente humano vuelve por WhatsApp;
   - al resolverse el ticket se cierra el handoff, la conversación queda resuelta **por un
     humano** (no se factura) y el agente IA vuelve a atender.

   La puerta de aprobación L3 **no** abre handoff: la aprobación se decide en el dashboard de
   Auyan y la IA sigue atendiendo.
4. **Toma humana desde el móvil.** Un `message.sent` que no salió de nuestra API
   (`source=whatsapp_business_app` o `sent_via=human`) significa que alguien de la marca
   contestó. Se registra como mensaje humano y se abre un handoff de tipo `device` que silencia
   al agente hasta **12 h sin actividad humana** (configurable por tenant). Un inbound con
   `metadata.standby=true` (el hilo lo lleva Meta Business Agent) no dispara el agente.
5. **Ventana de 24 h con el patrón del sector.** Antes de mandar cualquier mensaje que no sea la
   respuesta inmediata del agente (respuesta humana del handoff, confirmación de una aprobación
   L3), se comprueba la ventana. Si está cerrada:
   - se manda la **plantilla utility de re-enganche** del tenant;
   - el mensaje queda **pendiente** y se entrega cuando el comprador responda;
   - se deja una nota interna en el ticket con el estado de la ventana.

   Al abrir un handoff se anota hasta cuándo sigue abierta la ventana. **No hay nudges de cierre
   en WhatsApp**: caerían fuera de ventana.
6. **Identidad y L3.** El BSUID es el ancla principal del comprador y el teléfono en E.164 la
   secundaria. El gate de ownership L3 (en código, como #259) acepta que coincida el **email**
   **o** el **teléfono** del pedido. Si no coincide, o no hay teléfono (solo BSUID), bloquea y
   el agente ofrece pasar el caso a una persona. El OTP queda fuera (backlog post-piloto).
7. **Sesiones sobre un chat que no termina.** Se crea una conversación nueva de Auyan sobre el
   mismo chat de Zernio cuando la anterior está `closed`/`closed_abandoned` o lleva `resolved`
   más tiempo que la ventana de reapertura del billing (`reopen_window_days`, 7 por defecto).
   Si no, se reabre como hoy. Para eso hay que relajar `uq_conversations_external` para que
   solo aplique a las conversaciones vivas.
8. **Adjuntos y voz.**
   - Todo adjunto se descarga al llegar a un bucket privado de Supabase Storage (ruta con
     `tenant_id`).
   - Las **notas de voz se transcriben** tras una interfaz `Transcriber`. El proveedor sale de
     un mini-benchmark en español en C0 y tendrá su propio ADR, porque es un subprocesador
     nuevo de PII.
   - Las **imágenes** se guardan, el agente acusa recibo y van adjuntas al ticket si hay
     handoff. **Sin visión por ahora.**
9. **Intake con el patrón de ADR 0008.** El webhook valida, persiste y encola en una transacción
   y responde 200 al momento. El tenant se resuelve por `account.accountId`, con un índice único
   parcial como el de los helpdesks para que un id externo nunca apunte a dos tenants. La firma
   se valida con el secreto del tenant.

## Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| **WhatsApp nativo de cada helpdesk** (Zendesk messaging/Sunshine Conversations, Gorgias WhatsApp) | Ata el canal a la API de mensajería de cada helpdesk, distinta en cada uno. Los clientes sin ese add-on quedan fuera y no abre la puerta a DMs de Instagram/Facebook. Con Zernio es una sola integración. |
| **Meta Cloud API directa** | Obliga a Auyan a ser Tech Provider de Meta: verificación de negocio, Embedded Signup propio, tokens y webhooks por WABA. Son semanas de trámites que Zernio ya resuelve. La dependencia de Zernio se acota con el adapter y porque la WABA es del cliente. |
| **Una cuenta de Zernio por cliente** | Da aislamiento total, pero suma fricción de onboarding y contradice que el cliente no configure nada. La key limitada por profile da un aislamiento suficiente. |
| **Registrar Zernio como un "helpdesk" más** | Encajaría sin refactor, pero mezcla canal y equipo humano, y el escalado no tendría a dónde ir. |
| **Silenciar al agente solo con `status='escalated'`** | No sabe cuándo termina el handoff ni distingue la toma desde el móvil. |
| **Fuera de ventana: Direct Send `UTILITY`** | Depende de que la WABA sea elegible y de que Meta clasifique el texto como utility. No es el patrón del sector. |
| **Fuera de ventana: solo nota interna** | El comprador nunca recibe la respuesta humana. |
| **Una sola conversación por chat de WhatsApp** | El historial crece sin límite, mezcla temas y la reapertura interfiere con el billing. |
| **Visión con Claude para las fotos ya** | Cambia el formato de mensajes del grafo, el trace y el supervisor. Se deja para después. |

## Consecuencias

**Positivas:**
- WhatsApp funciona sin tocar el grafo. El agente recibe texto, con los audios ya transcritos.
- El handoff se reutiliza para cualquier helpdesk y cualquier canal de mensajería futuro
  (DMs de IG/FB por el mismo Zernio).
- Aislamiento por tenant: key limitada al profile, secreto de webhook propio e índice único por
  `accountId`.
- El cliente conserva su número y Auyan no tiene que hacer trámites con Meta.
- Arreglamos de paso `reply_delivered`, que en un canal no-helpdesk mentía.

**Negativas / costos asumidos:**
- Dependemos de un proveedor más (Zernio), con coste por cuenta conectada y posible add-on de
  inbox (se confirma en C0).
- Cada tenant necesita su plantilla de re-enganche aprobada por Meta, y hay dos triggers más en
  Zendesk por cliente (se crean con script).
- La transcripción suma un subprocesador de PII de voz, con su ADR y su DPA.
- Cuatro migraciones manuales más: índice de routing, handoffs, autor externo en mensajes y
  sesiones sobre `uq_conversations_external`. Además, el bucket de Storage.
- Aprobar o rechazar una L3 sigue sin serializarse con la cola de turnos (deuda de ADR 0008),
  también en WhatsApp.
- Mientras Zernio no publique el detalle de la firma, la verificación se basa en lo que se
  observe en C0 (fixture real en los tests).
