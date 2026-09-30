# Auyan — Estado actual

_Última actualización: 2026-10-01 (sesión 80: Sprint 2 implementado — PR-1 a PR-8 en la rama `ccr-7b4beddf-z9juh0`, pendiente de C0 y de las pruebas en vivo. Cabecera s77 → [`progress-archive.md`](progress-archive.md).)_
> _Sesión 80 (2026-09-30/10-01) — **Sprint 2 (WhatsApp vía Zernio) implementado de punta a punta en código, con Opus; falta C0 (Kenny) y el E2E en vivo.** Un commit por bloque del [plan](whatsapp-zernio-plan.md) en la rama `ccr-7b4beddf-z9juh0` (PR único contra `develop`): **PR-1** resolutor único del canal (`reply_delivered` ya no da por entregado WhatsApp); **PR-2** adapter + `/webhooks/zernio` (firma HMAC-SHA256 hex del body **confirmada en la doc oficial de Zernio**, dedupe `zernio:{event_id}`, routing por `accountId`, `standby`), identidad **BSUID → teléfono → email** y **sesiones** sobre el chat; **PR-2b** `scripts/onboard_whatsapp.py` + [runbook](runbooks/whatsapp-onboarding.md); **PR-3** formato de WhatsApp, **ventana de 24 h** (margen 10 min), plantilla de re-enganche una vez por chat, pendientes que se entregan en el siguiente inbound, `message.failed`; **PR-4** handoff modular (`HandoffTarget`, tabla `conversation_handoffs` con RLS) + Zendesk (ticket con transcripción literal, motivo y ventana); **PR-5** vuelta del handoff (triggers por script, respuesta pública → WhatsApp, `solved` → resuelta **sin facturar**) + toma desde el móvil (hold 12 h); **PR-6** ownership L3 por **email o teléfono** del pedido (fail-closed); **PR-7** adjuntos a Storage privado + `Transcriber` (adapter OpenAI **provisional y apagado**, ADR 0011 Propuesta) + mensajes fijos sin grafo; **PR-8** inbox con badge de WhatsApp, autor externo, adjuntos y aviso de handoff. **Validación:** 1700 tests verdes sin `.env` + ruff; **tests contra Postgres real** (handoffs/RLS + cola) y **prueba de humo integrada** `scripts/smoke_whatsapp_flow.py` (7 escenarios de webhook → cola → worker → entrega con Zernio/Zendesk/Storage simulados) en verde; todas las migraciones aplican en limpio. Bug de tests corregido: el fixture del registry dejaba vacío el `IntegrationRegistry` para el resto de la suite._
> _Sesión 79 (2026-09-30) — **Planificación del Sprint 2 (WhatsApp vía Zernio), solo docs, con Opus.** La API de Zernio se verificó en su OpenAPI (SDK oficial `zernio-dev/zernio-php`; `docs.zernio.com` bloqueado desde el contenedor). Hallazgos que cambian el diseño: el teléfono puede no llegar (**BSUID** de Meta desde abril de 2026); el código asumía `channel == helpdesk` en entrega, aprobaciones, escalado y cierre (`reply_delivered` daba por entregado cualquier canal no-helpdesk); un chat de WhatsApp no termina (hacen falta **sesiones**); los nudges de 48 h caerían fuera de la **ventana de 24 h**; `agent_human` exige un usuario de Auyan. Decisiones con Kenny: una cuenta Zernio de Auyan con **profile + API key limitada por tenant**; **handoff modular** (`HandoffTarget`, Zendesk primero) + silencio de la IA 12 h si la marca contesta desde el móvil (coexistence); fuera de ventana, **patrón del sector** (plantilla de re-enganche + entrega diferida); **transcribir notas de voz ya** (proveedor por mini-benchmark en C0); fotos a Storage y adjuntas al ticket; L3 por email **o** teléfono del pedido, si no → bloquear y ofrecer escalar (**OTP → backlog post-piloto**); sesión nueva si la anterior cerró o se resolvió hace >7 días; sin nudges en WhatsApp; E2E con sandbox y luego número real. [ADR 0010](adr/0010-whatsapp-zernio-handoff.md) (Propuesta) + [plan por PRs](whatsapp-zernio-plan.md). Implementación con Sonnet._
> _Sesión 78 (2026-09-30) — **Sprint 1 (bloque A) cerrado en lo que depende del código; queda A4 en vivo con Kenny.** **#260 + A2 #2:** los webhooks de Zendesk, Gorgias y Chatwoot ya no corren el grafo en el request: validan, reclaman la idempotencia, persisten y encolan en **una transacción** (`inbound_jobs`) → 200 en ~0,3–1,2 s. Un **worker en proceso** (lifespan) reclama por conversación con **advisory lock**: nunca hay dos turnos a la vez; las ráfagas se unen en una sola respuesta; hay heartbeat, recuperación tras crash, release en shutdown y reintentos con backoff ([ADR 0008](adr/0008-inbound-queue-postgres.md)). **A3 en vivo sobre Zendesk:** webhook duplicado ✅, ráfaga/simultáneos ✅ (sin solapes), credencial mala ✅ (`respond:undelivered`, sin resolver ni cobrar), trace LangSmith↔Supabase sin PII ✅. Bugs que salieron solo en vivo: carrera en el intake (`uq_end_customers_email` → 500), historial que terminaba en el agente (→ `error`), re-saludo, **el finalize de LangSmith pisaba `tenant_id`/`conversation_id` (ningún run correlacionaba)**, email/teléfono del cliente llegaban tal cual a LangSmith (ahora se enmascaran), e idempotencia en **409 permanente** tras un fallo (soft-delete no liberaba el `unique`). **A4 (preparación):** `refund_partial` mandaba `parent_id` nulo (Shopify lo rechaza) y `start_return` llamaba a un recurso REST que **no existe** → reescritos (transacción padre / GraphQL `returnCreate`). Gorgias estaba apuntando a Railway (reapuntado a Cloud Run). Tests de la cola contra **Postgres real** (`AUYAN_TEST_DATABASE_URL`). A4 11/11 en vivo con 5 bugs de Shopify/grafo corregidos. Sin mergear: rama `feature/sprint1-webhook-queue` ([PR #264](https://github.com/Auyan-ai/platform/pull/264)).)_

> Historial completo en [`docs/progress-archive.md`](progress-archive.md).

---

## 🔄 Contexto vigente

Kenny valida Auyan como **Managed AI Service** (Auyan pone el producto y opera integraciones, errores y tasa de resolución; sin self-serve). El repo solo contiene documentación técnica.

**Infra de staging (desde s77, Railway abandonado por falta de crédito):**
| Pieza | Dónde | Notas |
|---|---|---|
| API | **Cloud Run** `auyan-api-staging` · `https://auyan-api-staging-350779301730.europe-west3.run.app` | Proyecto GCP `auyan-510116`. Deploy: `apps/api/scripts/deploy_cloud_run.sh [.env.staging]` desde la raíz (sensibles → Secret Manager; SA dedicada; `min=0`, `max=1`, `--no-cpu-throttling`). `.env.staging` local, fuera de git. |
| Dashboard | **Vercel** `auyan-web-staging` · `https://auyan-web-staging.vercel.app` | Root `apps/web`, pnpm. `.vercelignore` en la raíz. |
| DB | Supabase `johidurhcobdkpvlnowl` (`eu-central-1`) | ⚠️ **Free tier: se pausa tras 7 días sin actividad** (pasó en s77). Antes del piloto: plan de pago o keep-alive. |
| Dominio | **`auyan.es`** (comprado s77) | Sin DNS configurado aún: `app-staging.`/`app.` → Vercel; API → ver custom domain en Cloud Run (`europe-west3` quizá no soporta domain mapping). Desbloquea Postmark. |
| Logs | Cloud Run → Logs (`gcloud logging read …`) | Reemplaza `railway logs`. |

- ~~🔴 Rotar el token de Shopify de Marea~~ → **descartado**: tienda demo sin datos reales (además la integración usa client credentials).
- **Registrar integraciones** ya no usa `railway run`: `set -a; . ./.env.staging; . ./.env.zendesk; set +a` y `python -m scripts.configure_staging_integrations …` desde `apps/api` (con `--dry-run` primero).

---

## ▶️ Arranque de la sesión 81 — C0 + pruebas en vivo del Sprint 2

1. Leer `CLAUDE.md`, este archivo, [ADR 0010](adr/0010-whatsapp-zernio-handoff.md), [ADR 0011](adr/0011-transcripcion-notas-de-voz.md) y el [plan](whatsapp-zernio-plan.md) (sección "Estado de implementación (s80)").
2. **C0 (Kenny):** cuenta Zernio + precios/Inbox add-on + DPA; `ZERNIO_API_KEY` en `.env.staging`; **fixture real de `webhook.test`** en `apps/api/tests/fixtures/zernio/webhook_test.json` (`{"secret", "headers", "raw_body"}`: el test que lo valida está marcado como pendiente); corpus de ~30 notas de voz en `apps/api/stt_bench/` → `scripts/benchmark_stt.py` → ADR 0011.
3. Red del entorno: permitir `zernio.com` para correr `onboard_whatsapp.py` desde una sesión.
4. Aplicar en staging las **4 migraciones del Sprint 2** (ver "🔴 Producción") **antes** del deploy, redeploy de Cloud Run y `setup_zendesk_handoff_triggers.py --tenant marea-studio`.
5. E2E con el sandbox (`onboard_whatsapp.py sandbox`) y luego la batería completa del plan → número real de Marea.

## 🚀 Próximos sprints (orden acordado s77)

Zernio/WhatsApp **sube de prioridad** (antes iba después de JEV): en España la inmensa mayoría de marcas atiende por WhatsApp. El **widget de chat** también es requisito del piloto. JEV baja al final.

### Sprint 1 — Cerrar el bloque A (E2E + robustez) · s78
- [x] ~~**A2 #2 · Advisory lock** por `(tenant_id, conversation_id)`~~ ✅ en el claim de la cola (ADR 0008).
- [x] ~~**[#260](https://github.com/Auyan-ai/platform/issues/260) · ack inmediato + grafo en background**~~ ✅ cola Postgres `inbound_jobs` + worker en proceso.
- [x] ~~**A3 restante**~~ ✅ en vivo sobre Zendesk (harness con webhook firmado): duplicado, ráfaga, 2º mensaje con el turno corriendo, credencial mala, trace sin PII + correlación.
- [x] ~~**Regresión Gorgias y Chatwoot**~~ → **bajo demanda** (decisión s78): la integración está montada y nuestro lado verificado en staging (webhook sintético → cola → grafo); la regresión en vivo se hace cuando un cliente lo pida. Hoy las cuentas de prueba están bloqueadas por plan (Chatwoot: API deshabilitada; Gorgias: cuota de mensajes). Gorgias ya apunta a Cloud Run.
- [x] ~~**A4 · Shopify**~~ ✅ **11/11 en vivo por Zendesk (s78)**. Scopes (12, app reinstalada) + Admin API **2024-10 → 2026-04** (Shopify ya servía 2025-10 en silencio). Pedidos de `carmenrosavegas@hotmail.com`: **L1 5/5**, **L2 2/2** (`tag_order`/`add_order_note` viven solo en el AOP `complaint`), **L3 4/4 aprobadas en el dashboard y verificadas en Shopify**: dirección #1432, reembolso 10 USD #1430 (cuelga de la transacción de cobro), devolución `#1431-R1` (Blusa, `too-small`), cancelación #1432. **Bugs que solo salieron en vivo, corregidos:** 🔴 un turno con error entregaba el **borrador sin supervisar** (propuesta de reembolso no aprobada); 🔴 `cancel_order` (REST) **cancelaba sin devolver el pago** → GraphQL `orderCancel` con reembolso + restock (verificado en #1433; #1432 reembolsado a mano); `start_return` sin motivo (Shopify lo exige → `returnReasonDefinitionId` de su librería); `refund_partial` con `parent_id` nulo y gateway vacío; queja que agotaba `max_tool_iterations` escalaba en seco sin responder. Limpieza: 25 aprobaciones de prueba de Lunaria (mayo) cerradas con soft delete. Decisión s78 ([#266](https://github.com/Auyan-ai/platform/pull/266)): una aprobación L3 **ejecutada** cierra **todas** las escalaciones abiertas de la conversación (antes un escalado previo dejaba el ticket `pending`, #29/#31); un **rechazo** solo cierra la del gate. Moneda → [#265](https://github.com/Auyan-ai/platform/issues/265).
- [x] ~~Merge de la rama `feature/sprint1-webhook-queue`~~ ✅ [#264](https://github.com/Auyan-ai/platform/pull/264).

### Sprint 2 — Zernio / WhatsApp (PRIORITARIO) · planificado s79, **implementado s80** (Opus) · falta C0 + E2E
Diseño: [ADR 0010](adr/0010-whatsapp-zernio-handoff.md) (Propuesta). **Plan paso a paso por PR, con archivos, tests y criterios de aceptación: [`whatsapp-zernio-plan.md`](whatsapp-zernio-plan.md).** El enum `channel_type` ya tiene `whatsapp`: no hace falta migración del enum.
**Regla dura (Kenny, s79): integración determinista.** Routing, sesiones, identidad, ownership, ventana, plantillas, handoff y silencio de la IA son código con tests, nunca decisión del LLM. Lo que no se puede razonar (imagen sin texto, audio ilegible, sticker) recibe un mensaje fijo del tenant, sin grafo. El LLM no gana libertades nuevas en este sprint.
- [ ] **C0 · Spike (Kenny):** cuenta Zernio + precios/Inbox add-on + quién paga a Meta + **DPA de Zernio** · key maestra en `.env.staging` · sandbox con el móvil de Kenny · **capturar la firma real del webhook** (fixture) · **mini-benchmark de voz a texto** (~30 notas en español; ElevenLabs Scribe v2 / OpenAI / Google Chirp UE / Wispr Flow / Voxtral o Gladia) → ADR 0011. Al cerrar: ADR 0010 → Aceptada.
- [x] ~~**PR-1** `refactor:` resolutor único del canal de entrega (sin asumir `channel == helpdesk`; arregla `reply_delivered`).~~ ✅ s80 (código + tests; falta E2E)
- [x] ~~**PR-2** `feat:` adapter Zernio + `/webhooks/zernio` (firma, dedupe por event id, routing por `accountId`, `standby`) + identidad BSUID/teléfono en el intake + **sesiones** sobre el chat + sin nudges en WhatsApp. Migración: routing + `uq_end_customers_phone` + `uq_conversations_external` solo para conversaciones vivas.~~ ✅ s80 (código + tests; falta E2E)
- [x] ~~**PR-2b** `chore:` `scripts/onboard_whatsapp.py` (`prepare` / `finalize` / `sandbox` / `offboard`: profile, key limitada, webhook, signup hospedado, plantilla de re-enganche) + runbook.~~ ✅ s80 (código + tests; falta E2E)
- [x] ~~**PR-3** `feat:` salida por WhatsApp: formato, **ventana de 24 h**, plantilla de re-enganche, mensajes pendientes que se entregan en el siguiente inbound, `message.failed`.~~ ✅ s80 (código + tests; falta E2E)
- [x] ~~**PR-4** `feat:` **handoff modular** (`HandoffTarget` + `conversation_handoffs` + la IA calla con handoff activo) + Zendesk (ticket con transcripción, motivo, ventana y adjuntos). Migraciones: handoffs + `agent_human` con autor externo. Revisión con Opus.~~ ✅ s80 (código + tests; falta E2E)
- [x] ~~**PR-5** `feat:` vuelta del handoff (triggers de Zendesk por script → respuesta humana por WhatsApp → `solved` cierra sin facturar) + **toma desde el móvil** (hold de 12 h). Revisión con Opus.~~ ✅ s80 (código + tests; falta E2E)
- [x] ~~**PR-6** `feat:` ownership L3 por email **o** teléfono del pedido (`phonenumbers`), fail-closed → ofrecer escalar. Revisión de seguridad con Opus.~~ ✅ s80 (código + tests; falta E2E)
- [x] ~~**PR-7** `feat:` adjuntos a Storage (bucket privado) + **transcripción de notas de voz** (`Transcriber`) + fotos adjuntas al ticket. ADR 0011.~~ ✅ s80 (código + tests; falta E2E)
- [x] ~~(opcional) **PR-8** `feat(web):` badge WhatsApp, autor externo e indicador de handoff en el inbox.~~ ✅ s80 (código + tests; falta E2E)
- [ ] **E2E:** sandbox (tras PR-3) → batería completa con el Zendesk de Marea (tras PR-7) → **número real de Marea** (criterio de cierre).

### Sprint 3 — Widget de chat + verificación de identidad · requisito del piloto
- [ ] **[#258](https://github.com/Auyan-ai/platform/issues/258) · Widget de chat** en la tienda (decidir construir vs. usar el del helpdesk).
- [ ] **[#257](https://github.com/Auyan-ai/platform/issues/257) · Verificación por niveles validada en código** (principio Decagon): resolutor de identidad antes de `reason`, ownership en código para cada skill sensible (el de teléfono llega en el Sprint 2), política por tenant y tier, sesión firmada (HMAC/JWT) para compradores logueados, lectura de `shop.customerAccountsV2`. ADR. **El OTP pasa al backlog post-piloto** (decisión s79, ver abajo).

### Sprint 4 — Memoria del cliente cross-canal
- [ ] **[#256](https://github.com/Auyan-ai/platform/issues/256):** resumen por conversación al cerrar (Haiku, sin PII sensible), identidad unificada email+teléfono (reusa la de sprints 2–3), inyección de los últimos 3–5 resúmenes, follow-ups de Zendesk, retención por tenant (GDPR). ADR.

### Sprint 5 — JEV en `select_aop` (shadow mode)
- [ ] Plan B de la s76 sin cambios (B0 spike → B1 shadow → B2 medición, con las fixtures de eval arregladas → B3 switch con flag + ADR).

### Backlog post-piloto (cuando haya piloto y negocio validado · decisión s79)
- [ ] **OTP al email/teléfono del pedido** (parte de [#257](https://github.com/Auyan-ai/platform/issues/257)): caducidad, intentos y auditoría. Hasta entonces, una L3 sin coincidencia de email o teléfono se bloquea y se ofrece escalar. Requiere Postmark con `auyan.es`.

### Backlog — omnicanal vía Zernio (s79)
- [ ] **DMs de Instagram → Facebook Messenger → TikTok**, sobre lo del Sprint 2: mismo webhook, adapter, cola, sesiones, handoff, adjuntos y transcripción. Por red: valor del enum (`messenger`/`tiktok`), `WindowPolicy` (Meta: 24 h + tag `HUMAN_AGENT` hasta 7 días para respuestas humanas, sin plantillas), formato de texto plano, mapeo de identidad y guard contra el historial que Zernio reproduce al conectar. **Límite:** esas redes no dan teléfono ni email → las L3 quedan bloqueadas (se ofrece escalar) hasta que exista el OTP. TikTok necesita un spike propio (ventana, límites, disponibilidad en la UE). Detalle: [plan § backlog omnicanal](whatsapp-zernio-plan.md#backlog--omnicanal-vía-zernio-instagram-facebook-messenger-tiktok).

### Transversal (encajar entre sprints)
- [ ] **App de Shopify de Auyan con OAuth (antes del 2º cliente).** La conexión actual (client credentials grant) **solo funciona si la app y la tienda son de la misma organización de Shopify** (doc oficial) → hoy cada cliente tendría que crear su propia app en su tienda, configurar scopes y pasarnos `client_id`/`client_secret`. Objetivo: una sola app de Auyan en el Dev Dashboard (distribución custom o pública) con OAuth *authorization code* (mismo patrón que `oauth_gorgias.py`/`oauth_zendesk.py`): scopes definidos una vez, el cliente instala y acepta; un scope nuevo = el cliente aprueba la actualización. El piloto puede ir con app por cliente.
- [ ] **Postmark con `auyan.es`** (DKIM/SPF) + SMTP de Supabase (magic links sin spam) — lo necesita el OTP por email.
- [x] ~~**ADR del cambio de plataforma** Railway → Cloud Run + Vercel~~ ✅ [ADR 0009](adr/0009-cloud-run-vercel.md) (s78). (`CLAUDE.md` + arquitectura ya actualizados al cierre de s77.)
- [ ] **Onboarding del cliente en Zendesk:** crear un agente de servicio "Auyan AI" y el OAuth client con ese usuario (hoy las respuestas salen firmadas por quien creó el client). Documentar en la guía de onboarding junto con el body del Trigger (solo IDs).
- [x] ~~**Supabase staging: keep-alive**~~ ✅ (s78) Cloud Scheduler `auyan-api-staging-keepalive`: `GET /health/ready` (consulta real a la base) a diario a las 06:00 Europe/Madrid → Supabase free no se pausa. Gratis (≤3 jobs).
- [x] ~~**Cloud Run `min-instances`**~~ → **implementado, apagado** (decisión s78: no se paga hasta tener un cliente de pago). `CLOUD_RUN_MIN_INSTANCES` en el `.env` del entorno (default 0). **Al firmar el primer cliente de pago: `CLOUD_RUN_MIN_INSTANCES=1` en el `.env` de producción y redeploy** (~63 USD/mes en `europe-west3`; con CPU siempre asignada no se puede bajar de 1 vCPU). Gratis ya aplicado: bytecode precompilado en la imagen → arranque del contenedor **~15 s → ~10,7 s**. [ADR 0009](adr/0009-cloud-run-vercel.md).
- [x] ~~**Alertas**~~ ✅ (s78) alerta en Cloud Monitoring con cualquier log `severity>=ERROR` del servicio → email a kennyrmv@gmail.com (máx. 1 cada 5 min, cierre automático a los 30 min). Requirió **logs JSON en Cloud Run** (`core/log_config.py`): antes los `logger.error` llegaban sin severidad (solo los tracebacks contaban como ERROR) y los `extra` (tenant_id, job_id…) se perdían. Todo con `apps/api/scripts/setup_cloud_run_ops.sh` (idempotente). **En producción: `ALERT_EMAIL=… SERVICE_NAME=auyan-api apps/api/scripts/setup_cloud_run_ops.sh`.**

---

## ✅ Hecho en s77 (E2E Zendesk sobre Marea, 2026-09-29/30)

| Escenario de la batería A3 | Resultado en vivo |
|---|---|
| ~~Consulta de pedido (L1)~~ | ✅ datos reales de Shopify (#1428 "Pendientes Aurora 29,90") |
| ~~Pedido inexistente / email sin pedidos~~ | ✅ pide confirmar, no inventa |
| ~~Resolución + cobro~~ | ✅ ticket `solved` + `resolution_event` (solo tras entrega confirmada, #249) |
| ~~Reapertura sin doble cobro~~ | ✅ `reverted_at` dentro de la ventana de 7 días |
| ~~Acción L3 → aprobación → ejecución~~ | ✅ cancelación #1428 y cambio de dirección #1429 aprobados en el dashboard de Vercel y ejecutados en Shopify |
| ~~Cierre tras aprobar~~ | ✅ escalación resuelta + ticket `solved` (#253) |
| ~~Escalado con razón explícita~~ | ✅ nota interna + grupo + `pending` |
| ~~Anti-loop~~ | ✅ la respuesta del agente no re-dispara el Trigger |
| ~~Ownership / privacidad~~ | ✅ desde otro email: no muestra ni modifica la dirección (#254/#259) |

Integraciones: ~~Zendesk E2E en vivo~~ ✅ (OAuth client_credentials, Trigger con body de solo IDs, firma HMAC). ~~Supabase Auth Site URL / Redirects~~ ✅ (apuntan a Vercel). ~~Auditoría s71 #3~~ ✅.

---

## Pendientes vivos

### 🔴 Producción (cuando `develop` pase a `main`)
Producción ya no puede ir en Railway: **definir su deploy** (Cloud Run `auyan-api` + Vercel prod, mismo script con otro `.env`) y aplicar a mano las migraciones: `l3_autonomy_acknowledgement` + `billing_resolution_events` + `add_gorgias_channel` + `add_inbound_jobs` (s78) + **Sprint 2 (s80), antes del deploy y en este orden:** `20261001000001_add_zernio_channel` (⚠️ pre-requisito: sin teléfonos duplicados por tenant, query en el archivo) + `20261001000002_add_conversation_handoffs` + `20261001000003_relax_agent_human_author` + `20261001000004_add_conversation_media_bucket`. El webhook de Zendesk falla abierto si falta `conversation_handoffs`, pero el worker de WhatsApp la necesita.

### Deuda técnica viva
- **Tests de queries contra un Postgres real en CI**: hay harness opcional (`tests/test_inbound_jobs_pg.py`, se activa con `AUYAN_TEST_DATABASE_URL`; en s78 cazó un cast `uuid→text`), pero CI no levanta Postgres. Siguiente paso: service container `postgres` en el workflow + extender a `db/queries.py`.
- **Approvals vs cola:** aprobar/rechazar una L3 no se serializa con los turnos inbound de la misma conversación (ADR 0008). Ídem las respuestas humanas del handoff (PR-5): sin carrera real porque la IA calla con handoff activo.
- **Sprint 2 (s80):** `packages/shared/src/api-types.ts` iba desfasado respecto de la API (~800 líneas) y solo se añadieron los esquemas nuevos → regenerarlo entero en un PR aparte. `find_outbound_message_by_platform_id` (cruce de `message.failed`/`message.sent`) busca en `messages.metadata` sin índice GIN: añadirlo si crece el volumen. La respuesta desde el dashboard de Auyan (`POST /conversations/{id}/reply`) solo guarda el mensaje, no lo entrega a ningún canal (ya era así). Verificar en el E2E que el scope OAuth de Zendesk permite `uploads` y `users:write`.
- `/webhooks/inbound` (script de pruebas) sigue síncrono y fuera de la cola.
- **Labels canónicos** (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`) no existen en el repo; los issues de s77 usan `enhancement`.
- **Fixtures de eval huérfanas** (slugs legacy ≠ canónicos; `smalltalk` sin fixture) → el promote gate falla "sin fixtures". Bloquea B2 (JEV).
- **Gorgias OAuth:** persistir `refresh_token` (`oauth_gorgias.py` lo descarta).
- `get_tool_permissions` en `db/queries.py` es código muerto.
- `mypy` estricto tiene ~1.8k errores preexistentes (no está en CI); `agents/nodes/reason.py` y algunos tests sin `ruff format` (`db/queries.py` y los routers de webhook ya formateados en s78).
- Fallback de idempotencia de Zendesk por hash de contenido: si el Trigger no manda `comment_id` y el cliente repite exactamente el mismo texto en el mismo ticket, el 2º se descarta (hoy el Trigger sí manda `comment_id`).
- Ventana de reapertura/billing: el cobro por resolución **no se activará con los primeros clientes** (decisión s77); se sigue registrando `resolution_events` como métrica de tasa de resolución.

### Deuda — Onboarding portal (Fase 2)

| Deuda | Severidad | Notas |
|---|---|---|
| Step 7 (Legal) pide aceptar DPA + Términos + GDPR sin links a documentos reales | media | El cliente acepta cláusulas que no puede leer. Crear `apps/web/app/(public)/legal/{dpa,terms,privacy}/page.tsx` + linkear desde los checkboxes. |
| Step 6 (KB) solo acepta texto pegado o URL | **alta** | Cliente real tiene PDFs/Word/Excel/imágenes. Pipeline: upload a Storage → worker extrae texto → `tenant_knowledge_submission` → aprobación normal. Cap 10 MB/archivo. |
| Imágenes laterales KREA pendientes (steps 4, 5, 6, 8) | baja | Placeholder dashed mientras tanto. Prompts en gstack/designs/. |

**Nota viva — Shopify content import (Fase 3):** importar pages/blogs/articles del Admin API (faq, devoluciones, envíos…) → markdown → cola `pending_review`. Reduce fricción del onboarding; no reemplaza el drop-zone.


---

## Estado general

| Área | Estado |
|---|---|
| Bloque 0 / 1 | ✅ completados y archivados. |
| Bloque 2 | Motor de billing por resolución mergeado (#234); Stripe pendiente; sin cobro por resolución a los primeros clientes. |
| Onboarding | Fase 1 ✅. Fases 2-4 pendientes ([`onboarding-system-plan.md`](onboarding-system-plan.md)). |
| Dogfood | **Marea Studio** (`683246c2-10ce-4f6c-a299-5053f32f8c01`, slug `marea-studio`): Zendesk `auyan.zendesk.com` (trial) + Shopify `marea-studio-dbljzahy`. Pedidos de prueba: **#1428** (cancelado) y **#1429** (`kenny.medina@ahoracrypto.com`, dirección cambiada). AOPs canónicos re-sembrados en s77. |
| Canales | Zendesk ✅ E2E en vivo (s77) + cola/A3 (s78) · Gorgias ⚠️ cuota de mensajes agotada (nuestro lado ✅) · Chatwoot ⚠️ API deshabilitada en la cuenta (nuestro lado ✅) · WhatsApp/Zernio 🧪 Sprint 2 implementado s80 (falta C0 + E2E; [ADR 0010](adr/0010-whatsapp-zernio-handoff.md) + [plan](whatsapp-zernio-plan.md) + [runbook](runbooks/whatsapp-onboarding.md)) · Widget ⏳ Sprint 3. |
| Suite | 1700 tests verde (sin `.env`, como CI; +20 contra Postgres real con `AUYAN_TEST_DATABASE_URL`) y prueba de humo `scripts/smoke_whatsapp_flow.py` (7 escenarios), ruff limpio. |
| ADRs | [`adr/`](adr/) (formato Nygard). 0008 cola inbound (s78), 0009 Cloud Run/Vercel (s78), **0010 WhatsApp/Zernio + handoff (s79, Propuesta)**, **0011 transcripción de notas de voz (s80, Propuesta hasta el benchmark de C0)**. Pendientes: verificación de identidad, memoria. |

---

## Deuda no prioritaria — Landing launch polish (2026-06-08)

No mover esto a "Empezar aquí" mientras el onboarding siga mandando.

| Deuda | Prioridad | Nota |
|---|---|---|
| Captura real de leads | baja | CTAs a correo/calendario por ahora; luego Tally/Typeform/Calendly o form propio. |
| Eventos de analytics | baja | CTAs principales, pricing, FP y sign-in cuando haya dominio/analytics final. |
| Legal mínimo público | media-baja | Privacy, Terms, Cookies y DPA antes de campañas amplias o tráfico pagado. |
| Favicon, OG social y marca final | baja | Al comprar el dominio. |
| QA post-deploy | baja | Canary visual + smoke en producción tras montar dominio/env vars. |
| Blog real o navegación sin blog | baja | Publicar 1 pieza SEO o esconder el link. |
| Páginas long-tail SEO | baja | `gorgias-ai-alternative`, `zendesk-ai-shopify`, `managed-ai-customer-support`… |

---

## Índice de documentos

**Norte (leer siempre):**
- `CLAUDE.md` — reglas operativas del proyecto (incluye la convención documental).
- [`progress.md`](progress.md) — este archivo: estado vigente + siguiente paso.

**Vivos (leer cuando el tema aplique):**
- [`architecture-overview.md`](architecture-overview.md) — punto de entrada técnico: stack, roles, onboarding, roadmap.
- [`architecture-agent-v2.md`](architecture-agent-v2.md) — mapa técnico del agente (compactado; en el detalle manda el código + tests).
- [`architecture-web.md`](architecture-web.md) — arquitectura de `apps/web`.
- [`DESIGN.md`](DESIGN.md) — sistema de diseño visual.
- [`billing-engine.md`](billing-engine.md) — motor de billing por resolución.
- [`onboarding-system-plan.md`](onboarding-system-plan.md) — plan del onboarding (Fases 1-4).
- [`whatsapp-zernio-plan.md`](whatsapp-zernio-plan.md) — plan del Sprint 2 (WhatsApp vía Zernio) por PRs; se archiva al cerrar el sprint.
- [`runbooks/whatsapp-onboarding.md`](runbooks/whatsapp-onboarding.md) — alta de WhatsApp (Zernio) por tenant y checklist de verificación.
- [`adr/`](adr/) — ADRs de arquitectura (formato Nygard).

**Históricos (nunca fuente de verdad — ver convención en CLAUDE.md):**
- [`progress-archive.md`](progress-archive.md) — historial de sesiones, sprints y secciones compactadas.
- [`archive/simulator-design.md`](archive/simulator-design.md) — diseño del simulator (implementado en 0.10).
- [`archive/aop-canonical-design.md`](archive/aop-canonical-design.md) — diseño de los AOPs canónicos (fuente real: `apps/api/aops/canonical.py`).
