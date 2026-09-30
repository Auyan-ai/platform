# Plan — Sprint 2: WhatsApp vía Zernio

> **Doc vivo.** Diseño: [ADR 0010](adr/0010-whatsapp-zernio-handoff.md). Cuando el sprint se cierre
> y se verifique en vivo, este doc pasa a `docs/archive/` con banner de histórico y la verdad queda
> en el código + tests.
>
> Planificado en la sesión 79 (2026-09-30) con Opus. La implementación va con **Sonnet**, un PR por
> bloque, cada uno contra `develop`. **Revisión con Opus** en PR-4/PR-5 (handoff y concurrencia) y
> en PR-6 (seguridad L3), como pide `CLAUDE.md`.

## Estado de implementación (s80)

Implementado PR-1 a PR-8 (un commit por bloque, rama `ccr-7b4beddf-z9juh0`, PR único contra
`develop`). Validado con la suite (sin `.env`), tests contra Postgres real y la prueba de
humo `apps/api/scripts/smoke_whatsapp_flow.py` (7 escenarios de punta a punta con Zernio,
Zendesk y Storage simulados). **Falta:** C0 (Kenny) y el E2E en vivo.

Ajustes respecto del plan, todos menores y deterministas:
- **Firma** confirmada en la documentación oficial de Zernio: `X-Zernio-Signature` = HMAC-SHA256
  en hex del body crudo (alias legacy `X-Late-Signature`). El test contra el fixture real de C0.4
  queda marcado como pendiente (se activa al guardar el fixture).
- **Plantilla de re-enganche:** si no hay nombre, `{{1}}` = "de nuevo" ("Hola de nuevo, …") en vez
  de "hola" ("Hola hola, …"). Se manda **una sola vez por chat** mientras haya pendientes.
- **Sandbox (staging):** el sandbox compartido no tiene profile, así que una key limitada por
  profile no lo ve: `onboard_whatsapp.py sandbox --staging` crea una key de alcance completo que
  caduca a los 30 días. Solo staging.
- **Handoff activo por chat**, no por conversación: si el cleanup cerró la sesión con el ticket aún
  abierto, la IA sigue callada en la sesión nueva.
- **Respuesta del equipo en un ticket ya resuelto:** se entrega y el handoff se **reabre** (el
  humano retomó la conversación).
- **Toma desde el inbox de Zernio** (`sentVia=human`) cuenta igual que la app del móvil.
- **Zendesk:** el scope OAuth suma `users:write` (requester del handoff); el script de triggers
  pide `read write` solo para operar.
- **Transcripción:** adapter OpenAI provisional **apagado por defecto** (`TRANSCRIPTION_PROVIDER`
  vacío → mensaje fijo). ADR 0011 queda en Propuesta hasta el benchmark.
- **PR-8:** `api-types.ts` ya iba desfasado; solo se añadieron los esquemas nuevos.

## Decisiones cerradas con Kenny (s79)

| Tema | Decisión |
|---|---|
| Cuenta Zernio | **Una cuenta de Auyan**, un **profile por tenant**, API key **limitada al profile** del tenant, cifrada en `tenant_integrations`. El número y la WABA son del cliente (Embedded Signup hospedado). |
| Handoff | **Ticket en el helpdesk del cliente** (Zendesk en este sprint) **y** detección de la toma desde el móvil (coexistence). **Módulo agnóstico de helpdesk**: interfaz `HandoffTarget`, Zendesk primera implementación. |
| Ventana de 24 h | **Patrón del sector** (Intercom/Zendesk/Gorgias): plantilla utility de re-enganche → el mensaje queda pendiente → se entrega cuando el comprador responde, más una nota interna en el ticket. |
| Audios | **Se transcriben ya.** Proveedor elegido por **mini-benchmark en C0**, detrás de una interfaz `Transcriber`. |
| Imágenes | Se **guardan** en Storage y van **adjuntas al ticket** si hay handoff. El acuse de recibo es un **mensaje fijo**, no del LLM (ver "Principio de determinismo"). Sin visión. |
| L3 por WhatsApp | Ownership por **email o teléfono** del pedido. Si no coincide o solo llega BSUID → **bloquear y ofrecer escalar**. **OTP → backlog post-piloto.** |
| Sesiones | Conversación nueva sobre el mismo chat si la anterior está `closed`/`closed_abandoned`, o `resolved` hace más de `reopen_window_days` (7 por defecto). Si no, se reabre. |
| Toma desde el móvil | El agente se calla hasta **12 h sin actividad humana** (configurable por tenant). |
| Nudges | **Desactivados en WhatsApp.** |
| E2E | **Sandbox de Zernio** durante el desarrollo, **número real de Marea** antes de cerrar el sprint. |

## Principio de determinismo (regla dura de este sprint)

Pedido de Kenny en la s79: la integración debe ser **lo más determinista posible**. El LLM no
gana ninguna libertad nueva en este sprint.

- **Todo lo que cambia estado, mueve datos o habla con un tercero es código con tests, nunca una
  decisión del LLM.** Eso incluye:
  - a qué tenant y conversación pertenece un mensaje (routing por `accountId`, sesiones);
  - quién es el comprador (BSUID/teléfono) y si es dueño del pedido (gate L3);
  - por dónde y a quién se entrega;
  - si la ventana está abierta, qué plantilla se manda y cuándo se entrega un pendiente;
  - cuándo se abre o se cierra un handoff y cuándo se calla la IA;
  - deduplicación e idempotencia, formato de salida y cortes.
- **El LLM solo hace lo que ya hacía:** decidir la intención (`select_aop`), redactar la
  respuesta, pedir skills (que pasan por los gates de código y de aprobación) y decidir escalar,
  supervisado.
- **Mensajes fijos, no generados, cuando no hay nada que razonar.** Se configuran por tenant y
  tienen un default en español:
  - acuse de una imagen sin texto;
  - audio que no se pudo transcribir o que supera la duración máxima;
  - adjunto que no se pudo descargar;
  - sticker o contenido sin texto.

  En esos casos **no se corre el grafo**. Si la imagen llega **con texto**, el grafo corre sobre el
  texto y el contenido lleva la marca `[adjuntó 1 imagen que no puedes ver; no describas su
  contenido]`, para que el LLM no se invente lo que hay en la foto.
- **Nada de resúmenes del LLM en el handoff.** La transcripción que va al ticket son los mensajes
  literales, formateados por código. El único texto del LLM ahí es el motivo del escalado, como ya
  pasa en Zendesk.
- **La transcripción de voz tiene que ser literal.** Se descarta cualquier proveedor que reescriba,
  resuma o "limpie" el texto: un número de pedido o un email mal reescrito es un error de
  integración, no de estilo. Es criterio eliminatorio en el benchmark de C0.

## Hechos verificados de la API de Zernio

Fuente: OpenAPI vía el SDK oficial `zernio-dev/zernio-php`. `docs.zernio.com` y `zernio.com` están
bloqueados desde el contenedor de Claude, y `github.com` también.

**Cómo consultar la API desde el contenedor** (lo único alcanzable es `raw.githubusercontent.com`,
con curl):
- Índice de endpoints y modelos:
  `https://raw.githubusercontent.com/zernio-dev/zernio-php/main/README.md`.
- Un grupo de endpoints: `…/main/docs/Api/<Grupo>Api.md`. Por ejemplo `MessagesApi`,
  `WebhooksApi`, `ConnectApi`, `ProfilesApi`, `APIKeysApi`, `WhatsAppApi`, `WhatsAppSandboxApi`,
  `AccountsApi`.
- Un modelo (payloads de webhooks y bodies): `…/main/docs/Model/<Modelo>.md`. Por ejemplo
  `WebhookPayloadMessage`, `WebhookPayloadMessageMessage`, `WebhookPayloadMessageMessageSender`,
  `WebhookPayloadMessageSent`, `WebhookPayloadMessageSentMessage`, `InboxWebhookAccount`,
  `InboxWebhookConversation`, `WebhookPayloadMessageMetadata`, `SendInboxMessageRequest`,
  `CreateApiKeyRequest`, `Webhook`.
- Los `.md` vienen con entidades HTML (`&#x60;` = backtick): pasarlos por `html.unescape`.

- Base: `https://zernio.com/api/v1`, `Authorization: Bearer <key>`. Los errores son JSON con `code`
  y `error`. Cada respuesta lleva `X-Request-Id`: loguearlo siempre.
- **Webhook** (`POST /v1/webhooks/settings`: `name`, `url`, `secret`, `events`, `profileIds`,
  `accountIds`, `customHeaders`; máximo 50 por usuario):
  - HMAC-SHA256 en `X-Zernio-Signature`. El id del evento viaja en `payload.id` y en
    `X-Zernio-Event-Id`, igual en reintentos y redeliveries.
  - La suscripción se autodesactiva tras 3 días sin ninguna entrega OK.
  - `POST /v1/webhooks/test` manda `event: "webhook.test"`. Hay logs (30 días) y redeliver.
- **`message.received`**:
  - `message`: `id`, `conversationId`, `platform`, `platformMessageId`, `direction`, `text`,
    `attachments[]`, `sender`, `sentAt`.
  - `sender`: `id`, `name`, `phoneNumber` (E.164, **puede faltar**), `businessScopedUserId`
    (ancla recomendada) y `whatsappUsername` (no estable).
  - `conversation`: `id` (id interno de Zernio, el que se usa para enviar),
    `platformConversationId`, `participantId`, `participantName`, `status`, `contactId`.
  - `account`: `id`/`accountId`, `profileId` (**falta en el sandbox compartido**), `platform`,
    `username`.
  - `metadata`: `standby` (el hilo lo lleva Meta Business Agent), `quotedMessageId`,
    `interactiveId`, `buttonPayload`…
  - `timestamp`.
- **Adjuntos de WhatsApp:** `url` apunta a `GET /v1/whatsapp/media/{mediaId}`, que **exige el
  Bearer**. Hay que descargarlos al llegar, porque Meta los borra.
- **`message.sent`:** `message.source` es `cloud_api` / `whatsapp_business_app` /
  `meta_business_agent`; `message.sentVia` es `human` / `api` / `broadcast` / `sequence` /
  `workflow` / … `message.failed` y `message.delivered` traen `error.code/title/message/explanation`.
- **Enviar:** `POST /v1/inbox/conversations/{conversationId}/messages`.
  - Body: `accountId` (obligatorio), `message`, `attachmentUrl`/`attachmentType`,
    `template: {elements:[{name, language, components}]}`, `category: "UTILITY"` (Direct Send;
    no lo usamos), `buttons`, `interactive`, `replyTo`.
  - Cabecera `Idempotency-Key`: misma key y mismo body devuelven la respuesta original; mismo
    body con otra key → 422; en curso → 409.
  - Límite de ~10 msg/min por destinatario (`400` con code `131056`). WhatsApp admite hasta
    4 096 caracteres por mensaje de texto (límite de Meta), así que cortamos en ≤4 000.
- **Plantillas:** `POST/GET/PATCH/DELETE /v1/whatsapp/templates`. Zernio resuelve el nombre y el
  idioma exactos antes de enviar. Si falla, devuelve `platform_api_error` con
  `phase: template_lookup`.
- **Onboarding:**
  - `POST /v1/profiles` (`name`).
  - `POST /v1/api-keys` (`scope: "profiles"`, `profileIds`, `permission`, `expiresIn`).
  - `GET /v1/connect/whatsapp?profileId=…&signup=hosted&brandName=…&language=es&redirect_url=…`
    devuelve `authUrl`. La página hospedada (co-branded) abre el Embedded Signup de Meta; al volver
    trae `connected=whatsapp&profileId&accountId&username`. El modo es coexistence por defecto
    (`onboarding=api` para un número que ya está en la Cloud API). Hay **un WhatsApp por profile**.
- **Sandbox:** `POST /v1/whatsapp/sandbox/sessions`. Número compartido, un teléfono por usuario;
  se activa cuando ese teléfono responde a la plantilla que manda el sandbox.
- **Thread control** (`POST /v1/inbox/conversations/{id}/thread-control`): solo con Meta Business
  Agent. No lo usamos, solo respetamos `standby`.

## C0 — Spike (manual, Kenny + sesión corta). Bloquea PR-2 (firma) y PR-7 (proveedor STT)

**Herramientas para C0 y operación** (s79):
- **MCP hospedado de Zernio** (`https://mcp.zernio.com/mcp`, más de 280 herramientas, OAuth).
  Página: `zernio.com/claude`. Plugin oficial: `zernio-dev/zernio-claude-plugin`. En las sesiones
  cloud se conecta como **conector de claude.ai** (`claude.ai/customize/connectors` → URL del MCP →
  login OAuth con la cuenta de Auyan en Zernio), y las sesiones lo cargan **al arrancar**. Sirve
  para C0: crear el profile de Marea, activar el sandbox, crear un webhook de prueba y mandar
  `webhook.test`, e inspeccionar payloads reales.
  - ⚠️ Tiene **el poder de la cuenta entera** (todos los profiles, es decir, todos los tenants).
    Solo para operación y staging, **nunca** en el runtime de la API (ADR 0010: el runtime usa
    keys limitadas por profile).
  - Lo que se configure a mano con el MCP hay que reproducirlo después con
    `scripts/onboard_whatsapp.py`, que es la fuente reproducible.
- **Red del entorno cloud:** la política actual bloquea `zernio.com` (la API vive en
  `https://zernio.com/api`), `mcp.zernio.com` y `docs.zernio.com`. Para correr desde una sesión
  los scripts de onboarding o el E2E hay que añadir esos dominios a los permitidos del entorno.
  Los tests no los necesitan: usan transport mock.

1. **Cuenta y precios.** Crear la cuenta de Auyan en Zernio y confirmar en la web oficial:
   - precio por cuenta conectada y si el **Inbox add-on** es de pago (los endpoints de inbox dicen
     "Requires Inbox addon");
   - **quién paga las tarifas de Meta** por conversación (método de pago en la WABA del cliente
     o crédito de Zernio);
   - **DPA de Zernio**: dónde aloja los mensajes, retención y si están en la UE. Zernio guarda
     todos los mensajes, así que es un subprocesador de PII.
   - Resultado → sección "C0" de este doc y ADR 0010 → **Aceptada**.
2. **Key maestra** en `.env.staging` (`ZERNIO_API_KEY`): solo la usan los scripts de operación,
   nunca el runtime.
3. **Sandbox:** activarlo con el móvil de Kenny.
4. **Firma del webhook:**
   - crear un webhook temporal hacia un capturador (webhook.site o similar, solo con
     `webhook.test`, sin PII) con un secreto conocido;
   - confirmar la cabecera exacta, la codificación (hex o base64) y qué se firma (raw body, o
     timestamp + body);
   - guardar el payload y las cabeceras como fixture en
     `apps/api/tests/fixtures/zernio/webhook_test.json`.
5. **Mini-benchmark de voz a texto** (`apps/api/scripts/benchmark_stt.py`, parte de PR-7a o
   antes si se quiere):
   - Corpus: unas **30 notas de voz reales** en `.ogg`/Opus grabadas por Kenny, su esposa y
     conocidos. Acentos de España y LatAm, ruido de calle, números de pedido dichos
     ("mil cuatrocientos treinta y dos"), emails deletreados y nombres de producto.
   - Transcripción de referencia hecha a mano. **El corpus no se commitea** (PII/voz): va en
     `apps/api/stt_bench/`, en `.gitignore`.
   - Candidatos: **ElevenLabs Scribe v2** (mejor WER batch entre los grandes según Artificial
     Analysis, julio de 2026), **OpenAI gpt-4o-transcribe**, **Google Chirp** (región UE, mismo
     proyecto GCP), **Wispr Flow API** (confirmar que da transcripción **literal**, sin
     auto-edits) y **Mistral Voxtral** o **Gladia** (empresas UE).
   - Métricas: WER con `jiwer` (dev-dependency), acierto en números de pedido/emails, latencia
     p50/p95, coste por minuto, acepta OGG/Opus sin convertir, **DPA, residencia UE y
     retención/zero-retention**.
   - Resultado → **ADR 0011** (proveedor de transcripción).

## PRs de implementación

Convenciones que aplican a todos:
- Rama `feature/…` o `claude/…`, PR contra `develop` y commits `feat:`/`fix:`/`chore:`.
- Type hints, errores explícitos (nunca silenciar) y test básico de toda función nueva.
- `ruff check` + `ruff format` de lo tocado. La suite completa pasa sin `.env`, como en CI.
- Migraciones en `supabase/migrations/` con timestamp nuevo. **Se aplican a mano** (psql / SQL
  Editor) y se listan en "Producción" de `progress.md`.
- Nada de PII ni secretos en LangSmith ni en los logs: allowlist, no denylist. Enmascarar
  teléfono y email como ya hace el intake.

### PR-1 · `refactor:` resolutor único del canal de entrega (sin Zernio todavía)

**Objetivo:** que ninguna parte del código asuma `conversation.channel == helpdesk`.

- `services/channel_routing.py` (nuevo):
  - `DELIVERY_ROUTES: dict[ChannelType, tuple[IntegrationKind, str]]` =
    `{"zendesk": ("helpdesk","zendesk"), "gorgias": ("helpdesk","gorgias"), "chatwoot": ("helpdesk","chatwoot"), "whatsapp": ("channel","zernio")}`.
  - `def delivery_route(channel) -> tuple[kind, provider] | None`.
  - `def is_messaging_channel(channel) -> bool` (`kind == "channel"`).
  - `async def load_delivery_client(conn, *, tenant_id, conversation) -> tuple[adapter, IntegrationContext] | None`:
    mueve aquí la lógica de `helpdesk_delivery.load_helpdesk_client`, usando
    `IntegrationRegistry.get(kind, provider)` y `get_active_integration(kind=…, provider=…)`.
- Sustituir los usos:
  - `inbound_worker._deliver_outcome`;
  - `helpdesk_delivery.deliver_message_to_helpdesk` (que llame al resolutor y mantenga el nombre,
    o lo renombre a `deliver_message_to_channel` con alias);
  - `approval_resolution.reply_delivered`: "tiene ruta de entrega" → exige `delivered`. Hoy
    pregunta al registry de helpdesk.
- `helpdesk_escalation` y `helpdesk_closure`: si `is_messaging_channel(channel)` → **no** hacen nada
  todavía (devuelven False y loguean `info`). PR-4 los enruta al handoff.
- **Tests:** mapping, `reply_delivered` con `whatsapp` sin entrega → False, y los existentes
  (`test_helpdesk_delivery`, `test_inbound_worker`, `test_approval_resolution`,
  `test_helpdesk_escalation`, `test_helpdesk_closure`) siguen verdes sin cambiar lo que comprueban.
- **Aceptación:** suite verde y cero cambio de comportamiento en Zendesk, Gorgias y Chatwoot.

### PR-2 · `feat:` adapter Zernio + webhook inbound + identidad + sesiones

**Depende de PR-1 y de C0.4 (firma).**

- **Migración `…_add_zernio_channel.sql`**:
  1. Índice único parcial de routing, espejo de `add_integration_routing_unique`:
     `(config->>'account_id') WHERE provider='zernio' AND kind='channel' AND deleted_at IS NULL AND is_active AND config->>'account_id' IS NOT NULL`.
  2. `uq_end_customers_phone` sobre `(tenant_id, phone)` donde `phone` no es nulo y no está
     borrado. Comprobar antes que no haya duplicados, con la query de pre-requisito comentada
     como en la migración de routing.
  3. **Sesiones:** recrear `uq_conversations_external` como
     `(tenant_id, channel, external_id) WHERE external_id IS NOT NULL AND deleted_at IS NULL AND status NOT IN ('closed','closed_abandoned','resolved')`.
     Así solo hay **una conversación viva** por chat y las cerradas o resueltas no bloquean.
     Revisar que `find_conversation_by_external` devuelva **la más reciente**
     (`ORDER BY created_at DESC LIMIT 1`).
- **`integrations/zernio.py`**:
  - `ZernioClient(api_key, *, transport=None)` sobre httpx. Timeout de 10 s, loguea
    `X-Request-Id` y traduce los errores a `ExternalIntegrationError` con el `code` de Zernio.
    Métodos: `send_text(conversation_id, account_id, text, idempotency_key)`,
    `send_template(conversation_id, account_id, name, language, components, idempotency_key)`,
    `download_media(url) -> (bytes, mime)` y `get_conversation(id)`.
  - `verify_zernio_signature(raw_body, secret, header) -> bool`, con comparación en tiempo
    constante y el algoritmo confirmado en C0.
  - `parse_zernio_event(payload) -> ZernioEvent`: dataclasses tipadas para
    `message.received` / `message.sent` / `message.failed` / `message.delivered` / otros, con
    normalización del teléfono a E.164.
  - `@IntegrationRegistry.register(kind="channel", provider="zernio") class ZernioAdapter`
    implementa `MessageProvider`. `send_outbound(ctx, conversation_ref, content)` manda el texto
    (el formateo y la ventana llegan en PR-3; aquí texto plano con corte a 4 000).
    `ctx.config` lleva `account_id`.
- **`routers/webhooks_zernio.py`** — `POST /webhooks/zernio`, mismo patrón que
  `webhooks_zendesk.py`:
  1. Parsear el JSON (400 si es inválido). Si `event == "webhook.test"` → 200.
  2. Obtener `account_id` (`account.accountId` o `account.id`) →
     `get_integration_by_zernio_account` (bootstrap, cross-tenant, como la query por subdomain).
     Si no existe → 404.
  3. Descifrar las credenciales y validar la firma con `credentials["webhook_secret"]`. Sin
     firma o inválida → 401. **Sin secreto → 500 y `logger.error`.** Zernio siempre firma, así
     que no se acepta nada sin firma.
  4. Tenant activo, `enforce_rate_limit` y `check_tenant_budget`, igual que Zendesk.
  5. Según el evento:
     - `message.received` con `direction=incoming`: si `metadata.standby` → 200 `ignored`.
       Si no → `persist_and_enqueue_inbound(...)` con `channel="whatsapp"`,
       `external_id=conversation.id`, `idempotency_key=f"zernio:{event_id}"`, `content=text`,
       identidad (abajo) y `attachments` en `message_metadata` (url, tipo, mime, sin descargar;
       la descarga va en el worker, PR-7).
     - `message.sent` / `message.failed` / `message.delivered`: en este PR solo se loguean
       (PR-3 y PR-5 los usan) → 200.
     - Cualquier otro evento → 200 `ignored`. **Nunca un 4xx/5xx por un evento desconocido**:
       Zernio reintentaría y acabaría desactivando el webhook.
  6. `notify_inbound_worker(request)`.
- **Intake e identidad** (`services/inbound_intake.py`, `db/queries.py`, `db/inbound_jobs.py`):
  - `persist_and_enqueue_inbound` acepta `customer_phone: str | None` y
    `customer_external_id: str | None` (BSUID con prefijo: `wa:bsuid:<id>`).
  - Orden de resolución del cliente: **external_id (BSUID) → teléfono → email → crear**. Al
    encontrarlo por teléfono sin external_id, se le asigna el BSUID si llega.
  - `lock_inbound_intake` añade las keys de teléfono y external_id (orden fijo).
  - Queries nuevas `find_end_customer_by_phone` / `find_end_customer_by_external_id`.
  - **Sesiones:** en `find-or-create`, si la conversación viva no existe pero hay una
    `resolved` dentro de `reopen_window_days` (de `billing_subscriptions` del tenant, 7 si no hay
    fila), se reabre (`reopen_if_resolved`). Si no, se crea una nueva. Solo para canales de
    mensajería; los helpdesks siguen igual.
- **Registry:** importar `integrations.zernio` donde se importan los demás adapters para que se
  registre.
- **`services/cleanup.py`:** saltar los nudges si `channel == "whatsapp"`. El cierre a las 48 h se
  mantiene.
- **`scripts/send_test_webhook.py`:** modo `--zernio` que firma un `message.received` sintético
  (para el harness de E2E).
- **Tests** (`tests/test_zernio_adapter.py`, `tests/test_webhooks_zernio.py`,
  `tests/test_inbound_intake.py`):
  - firma válida, inválida y ausente, con el fixture real de C0;
  - cuenta desconocida → 404; tenant inactivo → 403;
  - duplicado (`zernio:{event_id}`) → una sola fila;
  - `standby` ignorado; evento desconocido → 200;
  - sender solo con BSUID, solo con teléfono y con ambos (se une al cliente existente por
    teléfono);
  - dos intakes simultáneos del mismo número → un solo cliente y una sola conversación;
  - sesiones: viva → misma conversación, `resolved` hace 2 días → se reabre, `resolved` hace
    10 días → nueva, `closed` → nueva;
  - **cross-tenant:** una cuenta del tenant A nunca resuelve al B (test de índice/colisión, como
    `test_integration_routing_collision`);
  - sin nudge en WhatsApp.
- **Aceptación:** con el sandbox, un WhatsApp de Kenny → fila en `inbound_jobs` → el worker corre
  el grafo → la respuesta llega a su móvil. Trace en LangSmith con `channel=whatsapp` y el
  teléfono enmascarado.

### PR-2b · `chore:` onboarding de WhatsApp por script + runbook

**Puede ir con PR-2 si queda pequeño.**

- `apps/api/scripts/onboard_whatsapp.py` (reusa los helpers de cifrado y `_apply_plan` de
  `configure_staging_integrations`). Usa la key maestra `ZERNIO_API_KEY` y tiene
  `--dry-run`, como el otro script. Subcomandos:
  - `prepare --tenant <slug> --brand "<nombre>"`: crea o reusa el profile del tenant, crea la
    **API key limitada al profile** y el **webhook** (url `…/webhooks/zernio`; eventos
    `message.received`, `message.sent`, `message.failed`, `message.delivered`,
    `conversation.control_changed`, `account.disconnected`; `profileIds=[profile]`; secreto
    aleatorio de 32 bytes). Imprime el `authUrl` del **signup hospedado**
    (`signup=hosted&brandName=<marca>&language=es`) para mandárselo al cliente.
  - `finalize --tenant <slug>`: lee `GET /v1/accounts?profileId=…` y guarda en
    `tenant_integrations(kind='channel', provider='zernio')`:
    - `credentials = {api_key, webhook_secret}`;
    - `config = {profile_id, account_id, webhook_id, phone_number, reengagement_template: {name, language}}`.

    Luego crea la **plantilla de re-enganche** (categoría `UTILITY`, `es`), propuesta: *"Hola
    {{1}}, tenemos una respuesta sobre tu consulta. Responde a este mensaje para verla."* Sale
    en estado pendiente de aprobación de Meta.
  - `sandbox --tenant <slug>`: registra la cuenta del **sandbox compartido**. No tiene
    profile, así que el routing va por `account_id`. Solo un tenant de staging puede tenerla,
    lo garantiza el índice único.
  - `offboard --tenant <slug>`: borra el webhook y la key, y hace soft delete de la integración.
- **Runbook** `docs/runbooks/whatsapp-onboarding.md`: pasos con el cliente (Meta Business,
  coexistence o número nuevo, verificación), aprobación de la plantilla, alta de los triggers de
  Zendesk (PR-5) y checklist de verificación.

### PR-3 · `feat:` salida por WhatsApp — formato, ventana de 24 h, re-enganche y pendientes

**Depende de PR-2.**

- **Formato** (`integrations/zernio_format.py`): `to_whatsapp_messages(text) -> list[str]`.
  Convierte `**x**`→`*x*`, `__x__`/`_x_`→`_x_`, `# Título`→`*Título*`, `[txt](url)`→`txt: url`,
  quita el HTML y `&nbsp;`, y parte en trozos de ≤4 000 caracteres por párrafos. `ZernioAdapter`
  lo usa en `send_outbound`. `Idempotency-Key` = `f"{message_id}:{n}"`: el worker pasa el id
  del mensaje persistido; ampliar la firma de `send_outbound` con
  `idempotency_key: str | None = None` en el Protocol, opcional para los helpdesks.
- **Ventana** (`services/messaging_window.py`), con **nombre agnóstico de canal** para que el
  omnicanal futuro (ver el backlog al final) solo añada políticas:
  - `WINDOW_POLICIES: dict[ChannelType, WindowPolicy]`, donde `WindowPolicy` define la duración
    y qué hacer fuera de la ventana. **Solo se implementa `whatsapp`**: 24 h y plantilla de
    re-enganche.
  - `async def window_state(conn, *, tenant_id, conversation) -> WindowState(open: bool, closes_at: datetime | None)`,
    calculada con el **último mensaje inbound del comprador en ese chat de Zernio**. Es decir,
    todas las conversaciones de Auyan con el mismo `(channel, external_id)`, no solo la actual.
  - Margen de seguridad: se considera cerrada a partir de las **23 h 50 min**.
- **Entrega consciente de la ventana** (`services/channel_delivery.py`, o en el resolutor de
  PR-1):
  - `async def deliver_to_customer(conn, *, tenant_id, conversation, message) -> DeliveryResult(delivered|pending_window|failed)`.
  - En canales de mensajería, con la ventana cerrada:
    1. manda la plantilla `reengagement_template` del tenant con `{{1}}` = el nombre del
       comprador, o "hola" si no hay;
    2. marca el mensaje con `metadata.delivery = "pending_window"`;
    3. devuelve `pending_window`.
  - Si **no hay plantilla configurada o falla** → `failed`, `logger.error` y (desde PR-4) nota
    interna en el ticket.
  - Lo usan las **aprobaciones L3** (`deliver_message_to_helpdesk`) y, en PR-5, las respuestas
    humanas. La respuesta del turno del agente sigue el camino actual: acaba de llegar un inbound,
    así que la ventana está abierta.
- **Vaciar pendientes:** en el worker, **antes** del grafo y solo en canales de mensajería, se
  envían en orden los mensajes `pending_window` de la conversación (la ventana acaba de
  reabrirse) y se marcan `delivered`. Luego sigue el flujo normal (PR-4 decide si corre el grafo).
- **`message.failed`** (webhook): marca el mensaje saliente como `failed` (por
  `platformMessageId` guardado en `metadata` al enviar) y hace `logger.error` con
  `error.code/explanation`. Así se detectan `131056` (ritmo) y `131047` (ventana).
- **`approval_resolution`:** `pending_window` **no** cuenta como entregado. La conversación no se
  resuelve hasta entregar.
- **Tests:** conversiones de formato y cortes; ventana abierta/cerrada/en el margen y
  compartida entre sesiones; aprobación con la ventana cerrada → plantilla + pendiente →
  siguiente inbound → se vacía antes del grafo; plantilla ausente → `failed` + error;
  `message.failed` marca el mensaje; idempotencia de envío (reintento con la misma key).

### PR-4 · `feat:` handoff modular al helpdesk + implementación Zendesk (ida)

**Depende de PR-1 y PR-2. Revisión con Opus.**

- **Interfaz** (`integrations/base.py`):
  ```python
  @dataclass(frozen=True)
  class HandoffRequest:
      conversation_id: UUID
      customer_name: str | None
      customer_phone: str | None
      customer_email: str | None
      customer_ref: str            # end_customer_id → external_id del usuario en el helpdesk
      subject: str
      reason: str                  # razón explícita del escalado
      transcript: str              # últimos N mensajes, formateados
      window_closes_at: datetime | None
      attachments: list[StoredAttachment]
      channel_label: str           # "WhatsApp"

  class HandoffTarget(Protocol):
      async def open_handoff_ticket(self, ctx: IntegrationContext, req: HandoffRequest) -> ExternalTicketRef: ...
      async def append_customer_message(self, ctx: IntegrationContext, ticket_ref: str, content: str, attachments: list[StoredAttachment]) -> None: ...
      async def add_internal_note(self, ctx: IntegrationContext, ticket_ref: str, content: str) -> None: ...
  ```
- **Migración `…_add_conversation_handoffs.sql`**:
  - Tabla `conversation_handoffs`:
    - `id`, `tenant_id` (FK), `conversation_id` (FK compuesta con `tenant_id`);
    - `target` (`'helpdesk'|'device'`), `helpdesk_provider` (null si es `device`),
      `external_ticket_id`;
    - `status` (`'active'|'closed'`), `reason`, `opened_at`, `last_human_at`, `expires_at`
      (solo `device`), `closed_at`, `closed_reason`;
    - `created_at`, `updated_at`, `deleted_at`.
  - Índices únicos: uno **activo por conversación** y `(tenant_id, helpdesk_provider,
    external_ticket_id)` para lookup desde el webhook.
  - RLS igual que el resto de tablas de tenant, más el trigger `updated_at`.
  - Modelos Pydantic y queries en `db/`.
- **Migración `…_relax_agent_human_author.sql`**: permitir `role='agent_human'` sin
  `author_user_id` si `metadata ? 'external_author'`. Hoy `messages_human_has_author` lo
  impide, y el agente de la marca no es usuario de Auyan.
- **`services/handoff.py`**:
  - `open_handoff(tenant_id, conversation, reason)`:
    1. busca el **helpdesk primario** del tenant (`kind='helpdesk'`, `is_primary_for_kind`) y
       comprueba que su adapter implemente `HandoffTarget`;
    2. arma la transcripción (últimos 20 mensajes, "Cliente:"/"Agente IA:"/"Equipo:") y la
       ventana;
    3. abre el ticket y guarda la fila `active`;
    4. deja registro en el audit log (`AuditLogger`) con la razón.

    Si **no hay helpdesk primario** o falla → `logger.error` y la escalación interna queda
    visible en el dashboard de Auyan. Nunca revienta el turno.
  - `get_active_handoff(conn, tenant_id, conversation_id)`.
  - `forward_customer_message(...)`: añade el mensaje, con adjuntos y transcripción, al ticket.
  - `close_handoff(..., reason)`.
- **Enrutado del escalado:** `helpdesk_escalation.push_escalation_to_helpdesk_safe` hace
  `if is_messaging_channel(channel): return await open_handoff_safe(...)`. Así **todos** los
  caminos que ya escalan (grafo, `message_cap`, `handle_error`) abren handoff sin tocarlos.
  - **Excepción:** la puerta L3 (`escalation_reason` que empieza por
    `awaiting_human_approval:`) **no** abre handoff. La aprobación se decide en el dashboard de
    Auyan, la IA sigue atendiendo y la confirmación sale por la entrega que respeta la ventana
    (PR-3). Si se abriera, la IA quedaría callada con un ticket que nadie del helpdesk tiene que
    atender.
- **Worker:** en canales de mensajería, después de vaciar pendientes (PR-3) y **antes** del grafo:
  - handoff `helpdesk` activo → `forward_customer_message` y decisión `handoff_forwarded`;
  - handoff `device` activo y no vencido → decisión `human_hold`, sin reenviar;
  - handoff `device` vencido → `close_handoff(reason="device_hold_expired")` y sigue al grafo.
  - En ningún caso se corre el grafo con un handoff activo.
- **Zendesk** (`integrations/zendesk.py`), `ZendeskAdapter` implementa `HandoffTarget`:
  - `open_handoff_ticket`:
    1. `POST /api/v2/users/create_or_update` con `{name, phone, external_id: "auyan:<end_customer_id>", role: "end-user"}`;
    2. `POST /api/v2/tickets` con `requester_id`, `subject`, primer comentario **privado** (motivo +
       transcripción + "Ventana de WhatsApp abierta hasta HH:MM (hora de Madrid)"), `tags:
       ["auyan_handoff","auyan_whatsapp"]`, `group_id` = el `escalation_group_id` de la
       integración y los adjuntos como `uploads`
       (`POST /api/v2/uploads?filename=…` → token).
  - `append_customer_message`: comentario **público con `author_id` = requester**, para que el
    ticket se lea como una conversación normal, con los uploads si los hay.
  - **Verificar en el E2E:** una respuesta pública a un requester sin email no dispara email ni
    error visible, y el trigger de inbound actual **no** se dispara (el current user es el
    usuario API). Si molesta, pasar a nota interna (un flag en la config).
- **Tests:**
  - con handoff activo el worker no llama al grafo;
  - escalado en WhatsApp → `open_handoff`;
  - la puerta L3 (`awaiting_human_approval:`) **no** abre handoff;
  - tenant sin helpdesk primario → error logueado, sin excepción;
  - un solo handoff activo por conversación (dos escalados seguidos);
  - transcripción y adjuntos en la petición a Zendesk (transport mock);
  - `device` vencido → cierra y corre el grafo;
  - RLS de la tabla (lectura por otro tenant = 0 filas, siguiendo los tests de RLS/SQL que ya
    hay).

### PR-5 · `feat:` vuelta del handoff (Zendesk → WhatsApp), cierre y toma desde el móvil

**Depende de PR-3 y PR-4. Revisión con Opus.**

- **Triggers de Zendesk** (`apps/api/scripts/setup_zendesk_handoff_triggers.py`, idempotente, vía
  la Triggers API y el webhook ya existente):
  - **T1 "Auyan · handoff · respuesta"**: ticket actualizado, `current_tags` incluye
    `auyan_handoff`, comentario público y el usuario actual es agente. Body:
    `{"ticket_id","comment_id","subdomain","event":"handoff_reply"}`.
  - **T2 "Auyan · handoff · resuelto"**: el estado cambia a `solved` y tiene el tag. Body:
    `{"ticket_id","subdomain","event":"handoff_solved"}`.
  - Añadir la condición `tags no incluye auyan_handoff` al trigger de inbound actual. Además hay
    un guard en código.
- **`/webhooks/zendesk`**: tras resolver el tenant y validar la firma, si el ticket pertenece a
  un handoff (lookup por `(tenant, 'zendesk', ticket_id)`) **o** `event` empieza por `handoff_`,
  pasa a `services/handoff.handle_helpdesk_event` y **nunca** al intake normal (anti-loop).
  - `handoff_reply`:
    1. lee el comentario de la API; ignora los privados y los del usuario API de Auyan
       (`config.api_user_id`, se resuelve al configurar);
    2. guarda un `agent_human` con `metadata.external_author = {provider, id, name}`;
    3. `deliver_to_customer` (ventana → plantilla + pendiente + nota interna "ventana cerrada:
       enviamos la plantilla de re-enganche; tu respuesta se entregará cuando el cliente
       conteste");
    4. actualiza `last_human_at`.

    Idempotencia: `zendesk_handoff:{ticket}:{comment}` (misma tabla de idempotencia) y
    `Idempotency-Key` en Zernio.
  - `handoff_solved`: `close_handoff(reason="helpdesk_solved")` → la conversación queda
    `resolved` **sin** `resolution_event` (resolución humana, no se factura) y se cierran sus
    escalaciones abiertas. Si la ventana está abierta, **no** se manda mensaje de cierre al
    comprador: lo decide el humano.
  - Envío en línea con timeout corto: un solo POST a Zernio. Si falla → mensaje `failed`,
    `logger.error` y nota interna en el ticket. Aprobaciones y respuestas humanas siguen sin
    serializarse con la cola (deuda ADR 0008, sin carrera real porque el agente está en silencio).
- **Toma desde el móvil** (`webhooks_zernio`, evento `message.sent`):
  - si `source == "whatsapp_business_app"` o `sentVia == "human"`, y **no** es un
    `platformMessageId` nuestro:
    1. guarda un `agent_human` con `external_author = {provider: "whatsapp_business_app"}`;
    2. abre o renueva un handoff `device` con `expires_at = now + device_hold_hours` (12 por
       defecto, `tenant_config.extra.whatsapp_device_hold_hours`).
  - Si ya hay un handoff `helpdesk` activo, solo se registra el mensaje.
  - Idempotencia `zernio:{event_id}`.
- **Tests:**
  - respuesta pública del agente → llega a Zernio con la key idempotente;
  - un comentario privado, uno del usuario API o uno del requester → no se reenvían;
  - ventana cerrada → plantilla + pendiente + nota;
  - `solved` → conversación resuelta sin `resolution_event` y agente reactivado;
  - reintento de Zendesk → no duplica;
  - `message.sent` desde el móvil → hold de 12 h; nuestro propio `message.sent` (`sentVia=api`)
    → ignorado;
  - hold vencido → el agente vuelve;
  - el ticket de handoff nunca entra al intake normal.

### PR-6 · `feat:` ownership L3 por teléfono

**Depende de PR-2. Puede ir en paralelo a PR-3/4/5. Revisión de seguridad con Opus.**

- `SkillContext` suma `customer_phone: str | None` y `channel: str | None`. `build_skill_context`
  los toma de `state["end_customer"]` y `state["channel"]`.
- `services/identity.py`: `normalize_phone(raw, default_region) -> str | None` con la librería
  **`phonenumbers`**, dependencia nueva y estándar. La región por defecto sale de
  `tenant_facts` o de la config, `ES` si no hay. `phones_match(a, b) -> bool` (E.164 exacto).
- `_l3_ownership_error` (`agents/nodes/execute_skill.py`):
  - **pasa** si coincide el email (como hoy) **o** si coincide el teléfono del comprador con
    alguno de: `order.phone`, `customer.phone`, `shipping_address.phone` o
    `billing_address.phone`;
  - **fail-closed:** sin teléfono (solo BSUID), pedido sin teléfono o sin coincidencia → bloquea.
  - Mensaje de error por canal: en WhatsApp, *"no puedo verificar que el pedido sea tuyo desde
    este número; ofrécele al cliente pasar el caso a una persona del equipo"* (el agente escala →
    handoff). El log `l3_ownership_blocked` incluye `reason` (`no_customer_phone` /
    `phone_mismatch` / `order_unresolved`) y nunca el teléfono en claro.
- `get_order_status`: `is_owner` usa la misma función, así la dirección solo se muestra al dueño
  por email o teléfono.
- Revisar `ShopifyAdapter` para que los pedidos traigan `phone` y las direcciones (REST/GraphQL).
- **Tests:**
  - teléfono igual con formatos distintos (`+34 600…`, `600…`, `0034…`);
  - distinto; solo BSUID;
  - pedido sin teléfono;
  - email coincide aunque el teléfono no (pasa);
  - `get_order_status` no revela la dirección sin coincidencia;
  - regresión: todos los tests de `test_l3_order_ownership.py` y `test_address_privacy.py` siguen
    verdes.

### PR-7 · `feat:` adjuntos a Storage + transcripción de notas de voz

**Depende de C0.5 (proveedor), PR-2 y, para adjuntar al ticket, PR-4.**

- **Migración `…_add_conversation_media_bucket.sql`**: bucket **privado** `conversation-media` en
  `storage.buckets`. Sin políticas públicas: solo lo usa la service role.
- `services/media_storage.py`:
  - `store_attachment(tenant_id, conversation_id, message_id, idx, bytes, mime) -> StoredAttachment(path, mime, size)`
    vía la Storage REST API (`supabase_url` + `supabase_service_role_key`);
  - ruta `{tenant_id}/{conversation_id}/{message_id}/{idx}.{ext}`;
  - límite de 16 MB (el de WhatsApp).
- `integrations/transcription/`: `base.py` con el Protocol
  `Transcriber.transcribe(audio: bytes, mime_type: str, language: str = "es") -> Transcript(text, duration_s, provider, model, cost_usd)`
  y **un** adapter, el ganador de C0. Proveedor y key en `core/config.py`, opcionales: sin key,
  no se transcribe y el agente pide que lo escriba.
- **Worker**, pre-paso en canales de mensajería (antes de pendientes y handoff), para cada
  adjunto del inbound:
  1. `ZernioClient.download_media` → `store_attachment` → actualiza `messages.attachments`;
  2. **audio** → transcribir (máximo 5 min, configurable). El contenido del mensaje pasa a
     `"[Nota de voz] <transcripción>"`, con `metadata.transcription = {provider, model,
     duration_s, cost_usd}`, y el coste se suma a `UsageRecorder` del tenant;
  3. **imagen/archivo con texto** → el grafo corre sobre el texto, con la marca `[adjuntó 1
     imagen que no puedes ver; no describas su contenido]`;
  4. **sin texto útil** (solo imagen o archivo, sticker, audio que no se pudo transcribir o que
     supera la duración máxima, descarga fallida) → **mensaje fijo** del tenant
     (`tenant_integrations.config.media_fallback_messages`, con defaults en español), decisión
     `media_fallback` y **sin grafo**. Si falla algo → `logger.error`. **No** se reintenta el job
     por esto.

  Si hay handoff, los adjuntos van al ticket (PR-4 ya recibe `attachments`).
- **LangSmith:** child run `transcribe_audio` con provider, duración, latencia y coste, **sin**
  audio ni texto (el texto ya entra como contenido del turno, con las mismas reglas de PII).
- **Tests:**
  - audio → contenido transcrito y coste en uso;
  - imagen **con** texto → guardada, marca "no puedes verla" y el grafo corre;
  - imagen **sin** texto → mensaje fijo y **el grafo no se llama**;
  - descarga fallida, audio largo o sin proveedor → mensaje fijo, sin grafo y sin reintento;
  - ruta con `tenant_id`.
- **ADR 0011** (proveedor de transcripción) se mergea con este PR.

### PR-8 (opcional, pequeño) · `feat(web):` WhatsApp y handoff en el inbox

- Badge de canal WhatsApp.
- Mensajes `agent_human` con `external_author` → "Equipo de la marca (Zendesk)" o "Equipo de la
  marca (móvil)".
- Indicador de handoff activo en la conversación.
- Adjuntos: solo el nombre y el tipo. La vista previa con URL firmada va aparte.

## E2E en vivo

1. **Sandbox** (tras PR-2, PR-2b y PR-3), desde el móvil de Kenny:
   - consulta de pedido L1 → respuesta con formato de WhatsApp;
   - webhook duplicado (redeliver desde Zernio) → una sola respuesta;
   - ráfaga de 3 mensajes → una respuesta;
   - trace de LangSmith que correlaciona con Supabase, sin PII;
   - credencial mala → `respond:undelivered` y alerta.
2. **Batería completa** (tras PR-4 a PR-7), en el sandbox y con el Zendesk de Marea:
   - escalado → ticket en Zendesk con la transcripción, el motivo y la ventana → el comprador
     escribe → el mensaje aparece en el ticket y la IA calla → el agente de Marea contesta → le
     llega al comprador → `solved` → la IA vuelve a atender;
   - respuesta humana con la ventana cerrada, simulada ajustando la ventana en staging →
     plantilla → el comprador responde → se entrega lo pendiente;
   - L3 desde el teléfono del pedido → aprobación → confirmación por WhatsApp;
   - L3 desde otro teléfono → bloqueo y oferta de escalar;
   - nota de voz → transcripción → respuesta coherente;
   - foto → acuse de recibo y adjunta al ticket;
   - respuesta desde la app del móvil (**solo con el número real**, coexistence) → la IA calla 12 h.
3. **Número real de Marea** (Embedded Signup hospedado, coexistence o número nuevo): se repite la
   batería 2 más la plantilla propia aprobada. Este es el criterio de **cierre del sprint**.

## Qué queda fuera de este sprint

- OTP y verificación por niveles (#257, **backlog post-piloto**).
- Visión de imágenes con Claude.
- Handoff a Gorgias y Chatwoot (misma interfaz, cuando un cliente lo pida).
- DMs de Instagram, Facebook y TikTok (ver "Backlog — omnicanal vía Zernio" abajo). Los
  comentarios públicos y las reviews son otro producto (moderación pública).
- Vista previa de adjuntos en el dashboard.
- Serializar approvals con la cola (deuda de ADR 0008).
- Política de retención GDPR de adjuntos y transcripciones (Sprint 4, #256).

## Backlog — omnicanal vía Zernio (Instagram, Facebook Messenger, TikTok)

**No entra en este sprint.** Kenny quiere una experiencia omnicanal de verdad; el widget y el
email ya están resueltos aparte. Lo que construimos para WhatsApp está pensado para reusarse: el
canal va desacoplado del helpdesk, el handoff pasa por `HandoffTarget` y la ventana tiene
políticas por canal. Datos de la OpenAPI de Zernio, salvo lo marcado ⚠️, que hay que verificar.

**Se reusa tal cual** (un solo webhook, el mismo adapter y los mismos eventos para todas las redes):
`/webhooks/zernio`, `ZernioClient`/`ZernioAdapter` (mismo `POST …/messages`), intake + cola +
dedupe por `event id`, sesiones, **handoff al helpdesk** (la IA calla, el humano responde desde
Zendesk), descarga de adjuntos a Storage, transcripción de audios y mensajes fijos para lo que no
es texto. El onboarding es el mismo profile por tenant: Zernio admite una cuenta por plataforma y
profile, y se conecta por OAuth con `GET /v1/connect/{instagram|facebook|tiktok}`.

| | Instagram DM | Facebook Messenger | TikTok DM |
|---|---|---|---|
| Ventana | 24 h de Meta. Fuera de ella **no hay plantillas**: las respuestas **humanas** salen con el tag `HUMAN_AGENT` (Instagram solo admite ese), válido **7 días** según la política de Meta. | Igual: 24 h + `HUMAN_AGENT` para el humano. Hay otros tags de Facebook, pero no los usaríamos. | ⚠️ Reglas de ventana y límites de envío sin verificar. La disponibilidad de la API de mensajes de TikTok para negocios en la UE también está por confirmar. |
| Identidad | IGSID (id por cuenta). **Sin teléfono ni email.** | PSID (id por página). **Sin teléfono ni email.** | Id de TikTok. **Sin teléfono ni email.** |
| Consecuencia L3 | El gate de ownership **nunca** coincide → las L3 se bloquean y se ofrece escalar (o seguir por email/WhatsApp). Las L1 no muestran datos personales. El **OTP del backlog post-piloto** es lo que lo desbloquearía. | Igual. | Igual. |
| Adjuntos | URLs firmadas que **caducan** → descarga al llegar (mismo pipeline). | Igual. | Los no-texto llegan con `text` vacío + `tiktokMessageType` → mensaje fijo. |
| Contenido propio | Respuestas a stories, menciones, reels compartidos, `noRenderableContent`. | Botones postback / quick replies. | `share_post`, stickers, emoji. |
| Formato | Texto plano: no renderiza `*negrita*` de WhatsApp → formateador por canal. | Texto plano. | Texto plano. |
| Toma humana desde la app nativa | ⚠️ Verificar si Zernio emite `message.sent` cuando la marca contesta desde la app de Instagram o Meta Business Suite. | ⚠️ Igual. | ⚠️ Igual. |

**Cuidado propio de IG/FB:** al conectar la cuenta, Zernio **reproduce el historial previo** de DMs.
Guard determinista: nunca contestar mensajes con `sentAt` anterior a la conexión, o de más de N
minutos de antigüedad al llegar.

**Trabajo estimado por red** (pequeño si el Sprint 2 se implementa como está):
1. Valor en el enum `channel_type`: `instagram` ya existe; `messenger` y `tiktok` no → migración.
2. Ruta en `DELIVERY_ROUTES`.
3. `WindowPolicy` de la red.
4. Formateador de texto plano.
5. Mapeo de identidad.
6. Guard de historial.
7. Subcomando en `onboard_whatsapp.py`, que se renombraría a `onboard_messaging.py`.
8. Tests y E2E.

Orden sugerido: **Instagram → Facebook → TikTok**. En Instagram y Facebook la ventana y el tag
`HUMAN_AGENT` son de Meta y están documentados; TikTok necesita un spike propio.
