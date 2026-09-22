# Auyan — Estado actual

_Última actualización: 2026-07-17 (limpieza documental integrada con el estado de sesión 75: cabeceras s59-s71 y secciones cerradas → [`progress-archive.md`](progress-archive.md); `simulator-design` y `aop-canonical-design` → `docs/archive/`; `architecture-agent-v2.md` compactado. Regla en CLAUDE.md: máximo 3 cabeceras de sesión aquí — la más vieja se archiva al cerrar cada sesión.)_
> _Sesión 74 (2026-06-27) — **ADRs de arquitectura + case study para portafolio.** Kenny va a usar el proyecto como portafolio (target: roles freelance). Creado `docs/adr/` con 7 ADRs en formato Nygard (Contexto → Decisión → Alternativas → Consecuencias): [0001] multi-tenant `tenant_id`+RLS, [0002] modelo de negocio Managed AI Service, [0003] agente como grafo LangGraph, [0004] AOPs editables en runtime, [0005] skills L1/L2/L3 + approval, [0006] LangSmith observabilidad, [0007] model routing por tarea. Más `docs/case-study-auyan.md`: writeup narrativo para la web con ángulo founder/cliente/inversor, cada decisión enlaza a su ADR. Cumple lo que CLAUDE.md ya prometía (`docs/adr/`); `CONTEXT.md` sigue pendiente. **Solo docs — cero código, cero secrets/PII.** PR aparte contra `develop`. Sesión 73 abajo.)_
> _Sesión 73 (2026-06-27) — **LangSmith node-level tracing + fix crítico de seguridad.** Antes los traces de LangSmith solo mostraban `agent_conversation` → `agent_model_call` (tokens/costo agregados); el detalle nodo-por-nodo del grafo (select_aop, reason, execute_skill, supervise…) solo vivía en el dashboard de "Agent reasoning" (Supabase `reasoning_events`). [#237](https://github.com/Auyan-ai/platform/pull/237) MERGEADO: wrapper genérico `_traced` en `build_graph` emite un child run (`run_type=chain`) por cada nodo del grafo con nombre, duración y outputs allowlisteados — cero cambios en los nodos; `record_node_run` en `LangSmithClient`+`ObservabilityClient`; trace propagado vía `AgentState._trace_run_id/_trace_dotted_order` y `observability` en `AgentDependencies`. **🔴 Fix de seguridad [#238](https://github.com/Auyan-ai/platform/pull/238) MERGEADO (Kenny lo cazó en review):** el wrapper original mandaba el dict de output COMPLETO de los nodos sin allowlist a LangSmith (SaaS de terceros) → filtraba el **access token de Shopify descifrado** (`load_tenant_context.commerce_integration_ctx.credentials.token`) y **PII** (`load_conversation.conversation_history`/`end_customer`). El #237 alcanzó a mergearse y deployar con el leak antes del fix → el token estuvo en traces de los webhooks de prueba de hoy. Fix: **allowlist estricta** (`_NODE_OUTPUT_KEYS.get(name, [])` → nodo sin entrada emite `{}`, solo timing del span) + **redacción recursiva defensiva** (`_redact_dict` tacha token/credentials/secret/api_key/password/authorization) + 6 tests de regresión en `test_graph_tracing.py` (uno prueba que el token jamás aparece en el payload). 1323 verde, ruff/mypy limpios. **Verificado EN VIVO sobre Marea** (trace `f21ab9a7…`): child runs presentes, `execute_skill` muestra el tool call de Shopify, `load_tenant_context`/`load_conversation` sin credenciales ni PII. **🔴 PENDIENTE: rotar el access token de Shopify de Marea** (estuvo expuesto en LangSmith entre #237 y #238) → regenerar en Shopify + re-registrar con `railway run … configure_staging_integrations`. Aprendizaje guardado en memoria [[feedback_observability_no_secrets]]: observabilidad nunca exfiltra secrets/PII — allowlist, no denylist._
> _Sesión 72 (2026-06-21) — **Sesión autónoma: 3 PRs MERGEADOS (Zendesk managed-auth, latencia del AOP returns, motor de Billing Bloque 2), suite 1306 verde.** Kenny pidió cerrar los 3 pendientes técnicos dejándole solo Customer Discovery; lo manual quedó en "Arranque sesión 73". [#232](https://github.com/Auyan-ai/platform/pull/232) **Zendesk dual-auth** (API token/Basic, espejo de la s69 de Gorgias) + provider `zendesk` en `configure_staging_integrations`: el enum `channel_type` ya tenía `zendesk` → **sin migración**; el outbound usa el shape estándar (`add_comment` público), **sin** la rareza `source.type`/`body_html` de Gorgias. [#233](https://github.com/Auyan-ai/platform/pull/233) **latencia HOPS por prompt**: el AOP `returns` ahora secuencia "el dato va primero, la afirmación después" (verificar la política en KB/`tenant_facts`/`get_shop_policies` ANTES de afirmar un plazo) → mata de raíz el reject+retry del supervisor; test de invariante en `test_canonical_aops`. [#234](https://github.com/Auyan-ai/platform/pull/234) **motor de Billing Bloque 2** (PRD §7 puntos 1+3): migración `resolution_events` (append-only) + `billing_subscriptions` (snapshot de floor/included/overage, RLS solo-lectura, campos `stripe_*` nullable), conteo por periodo mensual anclado con **ventana de reapertura** (§2.3), catálogo de tiers (números **PROVISIONALES**), `compute_period_usage`, hooks en `respond`/`reopen`, y `GET /billing/usage` + `PUT /billing/subscription`. **Stripe NO entró** (necesita key + dashboard → siguiente trozo aditivo). Suite **1306 verde**, ruff/mypy limpios. **#232/#233/#234 MERGEADOS.** **🔴 Pendiente: aplicar a mano las migraciones de billing (#234) + la del piso L3 (#231) + `add_gorgias_channel` en prod** (Railway no corre SQL). Ver "🚀 Arranque sesión 73" abajo.)_

> Historial completo en [`docs/progress-archive.md`](progress-archive.md). Contexto estratégico en [`docs/auyan-master-context.md`](auyan-master-context.md).

---

## 🚀 Arranque sesión 76 — el outreach manda

**Modelo:** Sonnet para todo lo rutinario. Opus/Fable solo si vuelve a tocarse diseño del grafo, billing o RLS — que **no debería pasar este mes**.

**Foco único: GTM.** Plan vivo en [`gtm-plan-2026-07.md`](gtm-plan-2026-07.md); targets en [`discovery-targets.md`](discovery-targets.md); registro en [`outreach-log.csv`](outreach-log.csv).

1. **Formulario Tally** (9 preguntas de `customer-discovery.md` §6) — lo monta Kenny a mano, 10 min. Necesario antes de mandar mensajes que lo ofrezcan como fallback (el de Zapato Feroz no lo menciona → puede salir sin esperar).
2. **Mandar el primer mensaje.** Redactados y listos en `discovery-targets.md`. Registrar fecha/persona/canal/variante en el CSV.
3. **Cada viernes:** calcular tasas por cohorte/rol/variante. Si <20% de respuesta tras 15 mensajes → reescribir el mensaje, no insistir.
4. **Decidir el overage (€0,20 vs €0,25)** antes de la primera llamada de oferta — hay inconsistencia entre `billing-manual.md` (€/ticket) y `billing-resolution-prd.md` (€/resolución, manda). Ancla: COGS real medido €0,071/resolución (s64).
5. **Demo path (solo semana 3, contra un prospect real):** pulir las 2-3 pantallas que ese prospect vería (aprobaciones ✅ ya legible tras #241, conversaciones, razones de escalado). No pulir frontend antes: es build-first avoidance.

**⚠️ El calendario del GTM arrancaba el 2-jul y quedó parado** (Kenny volvió el 16-jul; el GTM se movió a otro chat). Re-anclar las semanas del plan a la fecha real de arranque antes de usarlo como cronograma.

**Track técnico — CONGELADO a propósito.** Solo se descongela si un prospect lo pide para SU piloto:
- **Zendesk E2E:** parado por decisión de Kenny hasta que un cliente lo pida expresamente (código listo, #232).
- **Latencia, billing (Stripe + suscripciones), backlog de la auditoría (#2 race de concurrencia, #3 outbound best-effort):** se mantienen como están. Detalle completo abajo en "Track técnico".
- **🔴 Sigue vivo de la s73:** rotar el access token de Shopify de Marea (estuvo expuesto en LangSmith entre #237 y #238).

---

## Track técnico — pendientes priorizados (CONGELADO; referencia)

**Modelo:** Sonnet para fixes acotados e integraciones; Opus para latencia (diseño del grafo), billing y RLS. Fable solo si Opus se queda corto (~2× el costo).

**Rama:** `develop` (sesión 72 mergeó #232–#234; sesión 71 mergeó #231). **Migraciones a mano** (Railway no corre SQL; [[reference_supabase_migrations]]):
- ✅ **Staging al día — aplicadas y VERIFICADAS EN VIVO (s72):** `20260617000000_add_l3_autonomy_acknowledgement.sql` (#231) + `20260621000001_add_billing_resolution_events.sql` (#234). Verificación E2E sobre Marea (un turno de devoluciones vía `/webhooks/inbound`): `respond` **sin** `agent_error` (fix L3 OK, antes escalaba todos los turnos), respondió la política real ("30 días desde la recepción", returns #233) y dejó la fila en `resolution_events` (billing #234). Comando: `railway run bash -c 'psql "$DATABASE_URL" -f <migración>'` — comillas SIMPLES para que la var la expanda Railway, no tu shell (si no: `database "lider" does not exist`).
- **🔴 PENDIENTE en PRODUCCIÓN:** cuando `develop` pase a `main`, aplicar a prod **las dos de arriba** + `add_gorgias_channel` (esta antes de que Gorgias salga en vivo allí). Lo aplicado arriba es **solo staging**.

**Pendientes (orden sugerido):**
1. **🔴/🟠 Backlog de la auditoría de robustez (de la s71, #231).** El hallazgo 🔴 L3-sin-approval ya está cerrado y mergeado. Quedan: **#2 race de concurrencia** — no hay lock por conversación; la idempotencia es por `message_id` (Chatwoot/Gorgias), así que 2 mensajes distintos del mismo cliente casi a la vez corren `process_inbound` en paralelo sobre el mismo state (sin checkpointer) → fix sugerido: advisory lock por `(tenant_id, conversation_id)`. **#3 entrega outbound best-effort** — `respond` marca `resolved` + cierra el ticket externo aunque `send_outbound` falle (cliente sin respuesta, ticket cerrado); fix: no marcar resuelto/cerrar hasta confirmar entrega. Menor: `get_tool_permissions` en `db/queries.py` es código muerto (sin callers).
2. **🟠 Zendesk — verificación E2E en vivo** (CÓDIGO listo, [#232] mergeado: dual-auth API token/Basic + provider `zendesk` en `configure_staging_integrations`). Falta: crear API token en un Zendesk sandbox → `railway run … configure_staging_integrations --tenant marea-studio --only zendesk` (con la `INTEGRATIONS_SECRET_KEY` de staging, o InvalidTag/500) → configurar el Trigger→Webhook → probar resolución/cierre/reapertura/escalado. Confirmar el outbound (`add_comment` público) contra la API real, como se hizo con Gorgias. (El enum `channel_type` ya tenía `zendesk` → sin migración.)
3. **🟡 Latencia — cerrar en vivo** (PROMPT listo, [#233] mergeado: el AOP `returns` verifica la política ANTES de afirmar plazos → mata el reject+retry del supervisor). Falta: `railway run -- … seed_canonical_aops --update` para que **Marea** herede el AOP nuevo → **curar `tenant_facts` de Marea** con la política de devoluciones (`return_window_days`, etc.) para que el agente la lea inyectada y se ahorre hasta el `get_shop_policies` → medir hops antes/después con `railway logs -d | grep llm_call` + traces. (Rollout de `smalltalk` a Lunaria/Purigu **descartado**: son simuladores, no aporta.)
4. **🟡 Billing — activar** (MOTOR listo, [#234] mergeado: `resolution_events` + conteo con ventana §2.3 + tiers + `GET /usage` + `PUT /subscription` + hooks). Falta: aplicar la migración (ver arriba) → crear la suscripción de cada tenant real (`PUT /billing/subscription` super_admin, o `upsert_billing_subscription`; sin ella `GET /usage` da 404 honesto) → **Stripe = siguiente trozo de código** (subscription=suelo, metered=overage + webhook; necesita `STRIPE_API_KEY` + productos/precios en su dashboard) → medir **COGS real** en LangSmith antes de fijar el overage (€0,20 vs €0,25; ancla €0,071 s64).
5. **🧭 Customer Discovery (foco estratégico, regla dura).** El [`market-analysis-2026-06.md`](market-analysis-2026-06.md) recomienda **bifurcar en 2 cohortes**: 5 e-commerce escenario 4 (quemados de Gorgias/Permut/GuruSup) + 5 comercializadoras de energía independientes (driver Ley 10/2025, deadline 28-dic-2026). NO pivotar; el dato decide. Pendientes de verificación antes de pitch: texto art. 2 Ley 10/2025, cliente Mundimoto↔Permut (sin fuente pública).

### Deuda técnica viva

- **Fixtures de eval huérfanas** (slugs legacy ≠ canónicos; `smalltalk` sin fixture) → el promote gate falla "sin fixtures" para los AOPs reales.
- **Chip:** persistir `refresh_token` en el OAuth de Gorgias (`oauth_gorgias.py` lo descarta → la integración OAuth se cae al caducar; el canal vivo usa Basic auth).
- Ticket de prueba 66116601 (Marea Gorgias) quedó `open` — residuo de debugging, cerrar a mano.
- README no existe en develop (si se crea, SIN "BPO" — contradice el posicionamiento).
- `get_tool_permissions` en `db/queries.py` es código muerto (sin callers).

---

## Estado general

| Área | Estado |
|---|---|
| Bloque 0 | ✅ 0.1–0.10. El 0.11 quedó cerrado operativamente vía dogfood Marea (L1 + L3 + resolución autónoma + Gorgias, todo E2E en vivo); la corrida formal 25/25+judge sobre Lunaria queda relegada. |
| Bloque 1 | ✅ 1.0–1.9 completados y archivados. 1.10 billing manual: runbook listo ([`billing-manual.md`](billing-manual.md)), depende de inputs externos por cliente. |
| Bloque 2 | Motor de billing por resolución mergeado (#234); Stripe pendiente (punto 4 arriba). Duet/Watchtower/Diagnostics sin arrancar. |
| Onboarding | Fase 1 ✅ ([#137](https://github.com/Auyan-ai/platform/pull/137)). Fases 2-4 pendientes — plan en [`onboarding-system-plan.md`](onboarding-system-plan.md); deuda del portal en tabla abajo. |
| Dogfood | **Marea Studio** verificado E2E: tenant `683246c2-10ce-4f6c-a299-5053f32f8c01` (slug `marea-studio`), pedido de pruebas #1181 (`order_id` interno `7133866033432`). Chatwoot de Marea/Purigu sin Teams → no setear `escalation_team_id`. |
| Suite | 1323 tests verde, ruff/mypy limpios (s73). |
| Portafolio | ADRs de arquitectura en [`adr/`](adr/) (7, formato Nygard) + case study [`case-study-auyan.md`](case-study-auyan.md) (s74). |

---

## 🧭 Foco estratégico — Customer Discovery

Regla dura (sesión 53, vigente): **el outreach manda**; no construir features nuevas sin conversaciones de discovery. **GTM arrancado (julio 2026):** plan vivo en [`gtm-plan-2026-07.md`](gtm-plan-2026-07.md), targets en [`discovery-targets.md`](discovery-targets.md), registro en [`outreach-log.csv`](outreach-log.csv). Bifurcado en 2 cohortes según [`market-analysis-2026-06.md`](market-analysis-2026-06.md): 5 e-commerce escenario 4 (quemados de Gorgias/Permut/GuruSup) + 5 comercializadoras de energía independientes (driver Ley 10/2025, deadline 28-dic-2026). NO pivotar; el dato decide. Plan operativo (ICP, mensajes, formulario): [`customer-discovery.md`](customer-discovery.md).

---

## Pendientes vivos

### Deuda — Onboarding portal (Fase 2)

| Deuda | Severidad | Notas |
|---|---|---|
| Step 7 (Legal) pide aceptar DPA + Términos + GDPR sin links a documentos reales | media | El cliente acepta cláusulas que no puede leer. Crear `apps/web/app/(public)/legal/{dpa,terms,privacy}/page.tsx` + linkear desde los checkboxes. |
| Step 6 (KB) solo acepta texto pegado o URL | **alta** | Cliente real tiene PDFs/Word/Excel/imágenes. Pipeline: upload a Storage → worker extrae texto → `tenant_knowledge_submission` → aprobación normal. Cap 10 MB/archivo. |
| Imágenes laterales KREA pendientes (steps 4, 5, 6, 8) | baja | Placeholder dashed mientras tanto. Prompts en gstack/designs/. |

**Nota viva — Shopify content import (Fase 3):** importar pages/blogs/articles del Admin API (faq, devoluciones, envíos…) → markdown → cola `pending_review`. Reduce fricción del onboarding; no reemplaza el drop-zone.

### Staging / servicios externos

| Pendiente | Estado |
|---|---|
| Migraciones | ✅ Staging al día (s72). 🔴 En **producción** faltan al pasar develop→main: `l3_autonomy_acknowledgement` + `billing_resolution_events` + `add_gorgias_channel`. Railway no corre SQL — a mano ([[reference_supabase_migrations]]). |
| LangSmith | ✅ Staging EU validado: `agent_conversation` + child runs por nodo (#237/#238), tokens/coste nativos. |
| Chatwoot Cloud | ✅ E2E verificado (Marea/Purigu). Registrar integraciones siempre vía `railway run … configure_staging_integrations` (cripto con la key de staging, si no InvalidTag/500). |
| Gorgias | ✅ E2E en vivo (s69, Basic auth; HTTP Integration con trigger *ticket-message-created*). |
| Zendesk | Código listo (#232, dual-auth). Falta E2E en vivo (punto 2 de Empezar aquí). |
| Shopify test store | ✅ Órdenes reales `auyan-e2e` en Lunaria (#1001-#1003) y Marea (#1181). **🔴 Rotar el access token de Marea** (expuesto en LangSmith entre #237 y #238): regenerar en Shopify + re-registrar con `railway run … configure_staging_integrations`. |
| Postmark | Pendiente: dominio aún sin comprar → DKIM/SPF bloqueado; luego plug como SMTP de Supabase. |
| Supabase Auth staging | Por confirmar: **Site URL** = `https://auyan-web-staging.up.railway.app` (si sigue en `localhost:3000` rompe magic links) + Redirect URLs. |
| Weekly Reports cron | Falta `DATABASE_URL` en GitHub Actions para el workflow programado. |

---

## Deuda no prioritaria — Landing launch polish (2026-06-08)

No mover esto a "Empezar aquí" mientras Customer Discovery + onboarding sigan mandando.

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
- [`auyan-master-context.md`](auyan-master-context.md) — negocio + arquitectura conceptual. Manda en lo conceptual.
- [`architecture-agent-v2.md`](architecture-agent-v2.md) — mapa técnico del agente (compactado; en el detalle manda el código + tests).
- [`architecture-web.md`](architecture-web.md) — arquitectura de `apps/web`.
- [`DESIGN.md`](DESIGN.md) — sistema de diseño visual.
- [`customer-discovery.md`](customer-discovery.md) — plan de discovery (foco actual).
- [`gtm-plan-2026-07.md`](gtm-plan-2026-07.md) — plan GTM julio 2026 (⚠️ re-anclar semanas: arrancaba 2-jul, quedó parado hasta 16-jul).
- [`discovery-targets.md`](discovery-targets.md) — 10 targets con mensajes redactados.
- [`outreach-log.csv`](outreach-log.csv) — registro de outreach (fecha/persona/canal/variante).
- [`market-analysis-2026-06.md`](market-analysis-2026-06.md) — análisis de mercado, cohortes, Ley 10/2025.
- [`adr/`](adr/) — 7 ADRs de arquitectura (formato Nygard) + [`case-study-auyan.md`](case-study-auyan.md) — portafolio.
- [`billing-manual.md`](billing-manual.md) — pricing/tiers + runbook de cobro manual.
- [`billing-resolution-prd.md`](billing-resolution-prd.md) — PRD del billing por resolución.
- [`onboarding-system-plan.md`](onboarding-system-plan.md) — plan del onboarding (Fases 1-4).

**Históricos (nunca fuente de verdad — ver convención en CLAUDE.md):**
- [`progress-archive.md`](progress-archive.md) — historial de sesiones, sprints y secciones compactadas.
- [`archive/simulator-design.md`](archive/simulator-design.md) — diseño del simulator (implementado en 0.10).
- [`archive/aop-canonical-design.md`](archive/aop-canonical-design.md) — diseño de los AOPs canónicos (fuente real: `apps/api/aops/canonical.py`).
