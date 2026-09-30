# Auyan — Estado actual

_Última actualización: 2026-09-30 (sesión 77: E2E en vivo de Zendesk, staging en Cloud Run + Vercel, seguridad L3. Cabecera s73 → [`progress-archive.md`](progress-archive.md).)_
> _Sesión 77 (2026-09-29/30) — **E2E en vivo de Zendesk + migración de staging a Cloud Run/Vercel + seguridad L3. 14 PRs mergeados ([#247](https://github.com/Auyan-ai/platform/pull/247)–[#259](https://github.com/Auyan-ai/platform/pull/259)) + [#261](https://github.com/Auyan-ai/platform/pull/261) abierto.** Railway se quedó sin crédito → **API en Google Cloud Run** (`europe-west3`, junto al pooler de Supabase `eu-central-1`; secretos en Secret Manager; `apps/api/scripts/deploy_cloud_run.sh`) y **dashboard en Vercel** (#251). Supabase staging estaba **pausado** (free tier) → restaurado. **Zendesk E2E en vivo** sobre Marea: 7 bugs que nunca se habrían visto sin tráfico real — API tokens retirados por Zendesk → OAuth `client_credentials` (#247); un stub en `routers/webhooks.py` **tapaba el webhook real** (#250); idempotencia por ticket (solo 1er mensaje) + anti-loop (#248); placeholder inexistente y **JSON roto por texto sin escapar** → el Trigger manda solo IDs y el comentario se lee de la API (#252). Auditoría s71 #3 cerrada: **solo se resuelve/cobra tras confirmar la entrega outbound** (#249). **Escalación L3 se cierra sola** tras aprobar/rechazar (#253). Mini-sprint UX (#254): dirección actual solo al dueño del pedido, limpieza de firmas/`&nbsp;`, confirmación con la dirección nueva, `address2`. **🔴 Bug crítico** `upsert_tool_permission` fallaba SIEMPRE (tipo ambiguo `$6`) → no se podían crear tenants ni cambiar permisos (#255). **🔴 Hueco de seguridad:** se podía modificar un pedido ajeno sabiendo solo el número → **gate de ownership en código** para toda L3 sobre pedido (#259). #261: el supervisor no veía la salida de las skills (rechazaba respuestas correctas y escalaba) + saludo en la 1ª respuesta. Investigación de verificación de identidad (Decagon/Sierra/Intercom/Chatbase/Gorgias) → issues #256–#258, #260. Kenny compró el dominio **`auyan.es`**. **Zernio/WhatsApp pasa a prioridad** (la mayoría de marcas en España usan WhatsApp).)_
> _Sesión 76 (2026-09-29) — **Planificación pre-piloto (solo docs, cero código).** Kenny define 3 frentes antes de firmar el primer piloto, en este orden: **A) E2E de integraciones** (piloto más probable sobre **Zendesk**, el único helpdesk sin E2E en vivo), **B) JEV** (clasificador tipado de TypeSafe, lanzado 2026-09-15) en `select_aop` en **shadow mode** primero, **C) Zernio** (API unificada de mensajería/redes, WhatsApp incluido) — **spike de descubrimiento a fondo** antes de diseñar; decisión tomada: los escalados de WhatsApp van por **handoff al helpdesk del cliente**. Plan detallado en "🚀 Empezar aquí — Plan pre-piloto" abajo. Implementación en sesiones siguientes._
> _Sesión 74 (2026-06-27) — **ADRs de arquitectura + case study para portafolio.** Kenny va a usar el proyecto como portafolio (target: roles freelance). Creado `docs/adr/` con 7 ADRs en formato Nygard (Contexto → Decisión → Alternativas → Consecuencias): [0001] multi-tenant `tenant_id`+RLS, [0002] modelo de negocio Managed AI Service, [0003] agente como grafo LangGraph, [0004] AOPs editables en runtime, [0005] skills L1/L2/L3 + approval, [0006] LangSmith observabilidad, [0007] model routing por tarea. Más `docs/case-study-auyan.md`: writeup narrativo para la web con ángulo founder/cliente/inversor, cada decisión enlaza a su ADR. Cumple lo que CLAUDE.md ya prometía (`docs/adr/`); `CONTEXT.md` sigue pendiente. **Solo docs — cero código, cero secrets/PII.** PR aparte contra `develop`. Sesión 73 abajo.)_

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

## 🚀 Próximos sprints (orden acordado s77)

Zernio/WhatsApp **sube de prioridad** (antes iba después de JEV): en España la inmensa mayoría de marcas atiende por WhatsApp. El **widget de chat** también es requisito del piloto. JEV baja al final.

### Sprint 1 — Cerrar el bloque A (E2E + robustez) · Opus para concurrencia/async
- [ ] **A2 #2 · Advisory lock** por `(tenant_id, conversation_id)` para 2 mensajes casi simultáneos. TDD.
- [ ] **[#260](https://github.com/Auyan-ai/platform/issues/260) · Webhooks: ack inmediato + grafo en background** con cola duradera (Postgres `SKIP LOCKED` o Cloud Tasks). Un turno de 28 s provocó reintentos de Zendesk; si se acumulan, Zendesk puede desactivar el webhook. Encaja con el lock.
- [ ] **A3 restante:** webhook duplicado, 2 mensajes simultáneos (tras el lock), fallo de outbound con credencial mala, trace LangSmith↔Supabase sin PII.
- [ ] **Regresión** de la batería en **Gorgias y Chatwoot** (tras todos los cambios de s77).
- [ ] **A4 · Shopify:** las 11 skills contra la tienda. Falta un pedido con **transacción real** (Bogus Gateway) para probar el **reembolso** (el #1428 se canceló pero no había cobro que devolver). La app de Marea necesita scopes `read_all_orders` (solo ve 60 días) y `read_locations` (el seed no puede crear pedidos con tracking).
- [ ] Merge de **[#261](https://github.com/Auyan-ai/platform/pull/261)** (supervisor + saludo; ya en staging).

### Sprint 2 — Zernio / WhatsApp (PRIORITARIO) · Opus diseño, Sonnet implementación
Ya verificado en su OpenAPI (s76): webhook `message.received` con HMAC (`X-Zernio-Signature`), dedupe por `X-Zernio-Event-Id`, respuesta con `POST /v1/inbox/conversations/{id}/messages`, **templates obligatorios** fuera de la ventana de 24 h, `profiles` por tenant, rate limit ~10 msg/min por destinatario, `thread-control` con Meta Business Agent, onboarding WhatsApp por API, SDK Python.
- [ ] **C0 · Spike** de catálogo + precios + **ADR** (qué adoptamos).
- [ ] **C1 · Decisiones:** handoff bidireccional (escalado → ticket en el helpdesk del cliente → respuesta humana vuelve por WhatsApp; silenciar al agente mientras el humano lleva la conversación) · una cuenta Zernio con profile por tenant vs cuenta por cliente · mapeo `profileId → tenant_id` con credenciales cifradas.
- [ ] **Identidad por teléfono:** el número de WhatsApp como identidad → ownership L3 por teléfono del pedido (primer paso de #257; si no coincide, OTP al email del pedido).
- [ ] **C2 · Implementación:** `integrations/zernio.py` + `routers/webhooks_zernio.py` (HMAC + dedupe + ack rápido, patrón de #260) + migración del enum `channel_type` + provider en `configure_staging_integrations` + tests + E2E en vivo con un número de prueba.

### Sprint 3 — Widget de chat + verificación de identidad · requisito del piloto
- [ ] **[#258](https://github.com/Auyan-ai/platform/issues/258) · Widget de chat** en la tienda (decidir construir vs. usar el del helpdesk).
- [ ] **[#257](https://github.com/Auyan-ai/platform/issues/257) · Verificación por niveles validada en código + OTP** (principio Decagon): resolutor de identidad antes de `reason`, ownership en código para cada skill sensible, OTP al email/teléfono **del pedido** (caducidad, intentos, auditoría), política por tenant y tier, sesión firmada (HMAC/JWT) para compradores logueados, lectura de `shop.customerAccountsV2`. ADR.

### Sprint 4 — Memoria del cliente cross-canal
- [ ] **[#256](https://github.com/Auyan-ai/platform/issues/256):** resumen por conversación al cerrar (Haiku, sin PII sensible), identidad unificada email+teléfono (reusa la de sprints 2–3), inyección de los últimos 3–5 resúmenes, follow-ups de Zendesk, retención por tenant (GDPR). ADR.

### Sprint 5 — JEV en `select_aop` (shadow mode)
- [ ] Plan B de la s76 sin cambios (B0 spike → B1 shadow → B2 medición, con las fixtures de eval arregladas → B3 switch con flag + ADR).

### Transversal (encajar entre sprints)
- [ ] **Postmark con `auyan.es`** (DKIM/SPF) + SMTP de Supabase (magic links sin spam) — lo necesita el OTP por email.
- [ ] **ADR del cambio de plataforma** Railway → Cloud Run + Vercel, y actualizar `CLAUDE.md` (sección Stack y regla de migraciones: "Railway deploya…") + `architecture-overview.md` / `architecture-web.md` — **propuesta pendiente de aprobación de Kenny** (CLAUDE.md lo modifica él).
- [ ] **Onboarding del cliente en Zendesk:** crear un agente de servicio "Auyan AI" y el OAuth client con ese usuario (hoy las respuestas salen firmadas por quien creó el client). Documentar en la guía de onboarding junto con el body del Trigger (solo IDs).
- [ ] **Supabase staging:** plan de pago o keep-alive antes del piloto.

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
Producción ya no puede ir en Railway: **definir su deploy** (Cloud Run `auyan-api` + Vercel prod, mismo script con otro `.env`) y aplicar a mano las migraciones: `l3_autonomy_acknowledgement` + `billing_resolution_events` + `add_gorgias_channel`.

### Deuda técnica viva
- **Tests de queries contra un Postgres real en CI**: todo va con mocks; el bug de #255 (tipo ambiguo en SQL) solo aparece al preparar la query.
- **Labels canónicos** (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`) no existen en el repo; los issues de s77 usan `enhancement`.
- **Fixtures de eval huérfanas** (slugs legacy ≠ canónicos; `smalltalk` sin fixture) → el promote gate falla "sin fixtures". Bloquea B2 (JEV).
- **Gorgias OAuth:** persistir `refresh_token` (`oauth_gorgias.py` lo descarta).
- `get_tool_permissions` en `db/queries.py` es código muerto.
- `mypy` estricto tiene ~1.8k errores preexistentes (no está en CI); `db/queries.py`, `routers/webhooks_zendesk.py`, `agents/nodes/reason.py` y algunos tests sin `ruff format`.
- Zendesk: el ticket **#2** de pruebas quedó `pending` (anterior a #253) → cerrar a mano.
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
| Canales | Zendesk ✅ E2E en vivo (s77) · Gorgias ✅ (s69, falta regresión) · Chatwoot ✅ (falta regresión) · WhatsApp/Zernio ⏳ Sprint 2 · Widget ⏳ Sprint 3. |
| Suite | 1407 tests verde (sin `.env`, como CI), ruff limpio. |
| ADRs | [`adr/`](adr/) (formato Nygard). Pendientes: plataforma Cloud Run/Vercel, Zernio, verificación de identidad, memoria. |

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
- [`adr/`](adr/) — ADRs de arquitectura (formato Nygard).

**Históricos (nunca fuente de verdad — ver convención en CLAUDE.md):**
- [`progress-archive.md`](progress-archive.md) — historial de sesiones, sprints y secciones compactadas.
- [`archive/simulator-design.md`](archive/simulator-design.md) — diseño del simulator (implementado en 0.10).
- [`archive/aop-canonical-design.md`](archive/aop-canonical-design.md) — diseño de los AOPs canónicos (fuente real: `apps/api/aops/canonical.py`).
