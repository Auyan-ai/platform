# Auyan — Estado actual

_Última actualización: 2026-09-29 (sesión 76: planificación pre-piloto — E2E integraciones, JEV, Zernio. Cabecera s72 → [`progress-archive.md`](progress-archive.md).)_
> _Sesión 76 (2026-09-29) — **Planificación pre-piloto (solo docs, cero código).** Kenny define 3 frentes antes de firmar el primer piloto, en este orden: **A) E2E de integraciones** (piloto más probable sobre **Zendesk**, el único helpdesk sin E2E en vivo), **B) JEV** (clasificador tipado de TypeSafe, lanzado 2026-09-15) en `select_aop` en **shadow mode** primero, **C) Zernio** (API unificada de mensajería/redes, WhatsApp incluido) — **spike de descubrimiento a fondo** antes de diseñar; decisión tomada: los escalados de WhatsApp van por **handoff al helpdesk del cliente**. Plan detallado en "🚀 Empezar aquí — Plan pre-piloto" abajo. Implementación en sesiones siguientes._
> _Sesión 74 (2026-06-27) — **ADRs de arquitectura + case study para portafolio.** Kenny va a usar el proyecto como portafolio (target: roles freelance). Creado `docs/adr/` con 7 ADRs en formato Nygard (Contexto → Decisión → Alternativas → Consecuencias): [0001] multi-tenant `tenant_id`+RLS, [0002] modelo de negocio Managed AI Service, [0003] agente como grafo LangGraph, [0004] AOPs editables en runtime, [0005] skills L1/L2/L3 + approval, [0006] LangSmith observabilidad, [0007] model routing por tarea. Más `docs/case-study-auyan.md`: writeup narrativo para la web con ángulo founder/cliente/inversor, cada decisión enlaza a su ADR. Cumple lo que CLAUDE.md ya prometía (`docs/adr/`); `CONTEXT.md` sigue pendiente. **Solo docs — cero código, cero secrets/PII.** PR aparte contra `develop`. Sesión 73 abajo.)_
> _Sesión 73 (2026-06-27) — **LangSmith node-level tracing + fix crítico de seguridad.** Antes los traces de LangSmith solo mostraban `agent_conversation` → `agent_model_call` (tokens/costo agregados); el detalle nodo-por-nodo del grafo (select_aop, reason, execute_skill, supervise…) solo vivía en el dashboard de "Agent reasoning" (Supabase `reasoning_events`). [#237](https://github.com/Auyan-ai/platform/pull/237) MERGEADO: wrapper genérico `_traced` en `build_graph` emite un child run (`run_type=chain`) por cada nodo del grafo con nombre, duración y outputs allowlisteados — cero cambios en los nodos; `record_node_run` en `LangSmithClient`+`ObservabilityClient`; trace propagado vía `AgentState._trace_run_id/_trace_dotted_order` y `observability` en `AgentDependencies`. **🔴 Fix de seguridad [#238](https://github.com/Auyan-ai/platform/pull/238) MERGEADO (Kenny lo cazó en review):** el wrapper original mandaba el dict de output COMPLETO de los nodos sin allowlist a LangSmith (SaaS de terceros) → filtraba el **access token de Shopify descifrado** (`load_tenant_context.commerce_integration_ctx.credentials.token`) y **PII** (`load_conversation.conversation_history`/`end_customer`). El #237 alcanzó a mergearse y deployar con el leak antes del fix → el token estuvo en traces de los webhooks de prueba de hoy. Fix: **allowlist estricta** (`_NODE_OUTPUT_KEYS.get(name, [])` → nodo sin entrada emite `{}`, solo timing del span) + **redacción recursiva defensiva** (`_redact_dict` tacha token/credentials/secret/api_key/password/authorization) + 6 tests de regresión en `test_graph_tracing.py` (uno prueba que el token jamás aparece en el payload). 1323 verde, ruff/mypy limpios. **Verificado EN VIVO sobre Marea** (trace `f21ab9a7…`): child runs presentes, `execute_skill` muestra el tool call de Shopify, `load_tenant_context`/`load_conversation` sin credenciales ni PII. **🔴 PENDIENTE: rotar el access token de Shopify de Marea** (estuvo expuesto en LangSmith entre #237 y #238) → regenerar en Shopify + re-registrar con `railway run … configure_staging_integrations`. Aprendizaje guardado en memoria [[feedback_observability_no_secrets]]: observabilidad nunca exfiltra secrets/PII — allowlist, no denylist._

> Historial completo en [`docs/progress-archive.md`](progress-archive.md).

---

## 🔄 Retomada (2026-09) — modelo managed, repo solo técnico

Kenny retoma el proyecto para validarlo como **Managed AI Service**: Auyan pone el producto y opera integraciones, errores y mejora de la tasa de resolución. Sin self-serve.

El repo queda **solo con lo relacionado con código**: se eliminaron los docs de negocio/GTM (auditoría de viabilidad, market analysis, discovery, GTM plan, case study, billing manual, outreach log, master context, ADR 0002). Lo técnico del master context pasó a [`architecture-overview.md`](architecture-overview.md) y lo técnico del PRD de billing a [`billing-engine.md`](billing-engine.md).

**Track técnico:** se mantiene como está abajo en "Track técnico".
- **🔴 Sigue vivo de la s73:** rotar el access token de Shopify de Marea (estuvo expuesto en LangSmith entre #237 y #238).

---

## 🚀 Empezar aquí — Plan pre-piloto (s76, 2026-09-29)

Orden acordado: **A → B → C**. Piloto más probable: cliente Shopify con **Zendesk**. El "Track técnico" de abajo queda como referencia; lo que se solapa (Zendesk E2E, backlog de auditoría) se ejecuta desde aquí.

### A. E2E de integraciones — bloquea firmar el piloto

**Modelo:** Sonnet para E2E y adapters; Opus para A2 (concurrencia).

- **A0. Higiene previa:** 🔴 rotar el token de Shopify de Marea (s73) · confirmar Site URL + Redirect URLs de Supabase Auth staging (magic links del `tenant_admin`).
- **A1. Zendesk E2E en vivo** (código listo en #232, nunca probado): sandbox Zendesk + API token → `railway run … configure_staging_integrations --tenant marea-studio --only zendesk` → Trigger→Webhook → batería A3.
  - **Verificación extra:** ticket originado en **messaging/WhatsApp nativo de Zendesk** → ¿el `add_comment` público le llega al usuario final o hace falta Sunshine Conversations? Eso decide si el WhatsApp del piloto puede ir por Zendesk nativo sin Zernio (ver C1).
- **A2. Cerrar el backlog de la auditoría s71** (con tráfico real deja de ser teórico): **#3** no marcar `resolved` ni cerrar el ticket hasta confirmar la entrega outbound; **#2** advisory lock por `(tenant_id, conversation_id)` para serializar mensajes seguidos. TDD.
- **A3. Batería de escenarios común** — primero Zendesk, después regresión en Gorgias y Chatwoot:

  | Escenario | Esperado |
  |---|---|
  | Consulta de pedido (L1 `get_order`) | responde con datos reales, resuelve, fila en `resolution_events` |
  | Política (AOP `returns`) | responde desde `tenant_facts`/KB, sin reject+retry del supervisor |
  | Acción L3 (cancelar/devolver) | approval pendiente → aprobar en el dashboard → se ejecuta en Shopify → confirma al cliente |
  | Escalado | ticket asignado a humano + nota interna con contexto y **razón explícita** |
  | Reapertura tras resolver | reabre dentro de la ventana §2.3, sin doble conteo en billing |
  | Webhook duplicado (retry) | idempotente, una sola respuesta |
  | 2 mensajes casi simultáneos | serializados (después de A2) |
  | Fallo de outbound (credencial mala) | **no** se marca resuelto; error logueado y alertado |
  | Trace | LangSmith correlaciona con conversación/audit log de Supabase; sin secrets ni PII |

- **A4. Shopify:** las 11 skills (5 L1, 2 L2, 4 L3) contra la tienda de pruebas con órdenes seed (`seed_shopify_e2e_orders`).
- **A5. Postmark:** sigue bloqueado por el dominio → fuera del piloto salvo que se compre antes.
- **Entregable:** checklist reproducible por helpdesk (runbook o script `scripts/`, a decidir en la sesión) + resultado registrado aquí.

### B. JEV en `select_aop` — shadow mode primero

**Qué es:** JEV (TypeSafe) no genera texto; recibe estado + preguntas tipadas (`Choice` ≤255 opciones / `Score` / `Noul` sí-no) y devuelve **probabilidades calibradas** en ~100 ms, a ~$0,042/M tokens de input (output gratis). Contexto ~32k tokens, solo texto. Lanzado el 2026-09-15, en early access.
**Por qué encaja:** hoy Haiku *inventa* la `confidence`; con JEV sería una probabilidad calibrada que alimenta directo la histéresis existente (`intent_min_confidence` / `intent_switch_threshold`).
**Modelo:** Opus para el diseño (nodo del grafo), Sonnet para el cliente HTTP.

- **B0. Spike (gate — si falla, se congela):** acceso a la API · calidad en **español** · **DPA / residencia UE / retención** (le mandaríamos mensajes del cliente final = PII; si no hay garantías → redactar con `services/pii` antes de enviar) · latencia real desde Railway.
- **B1. Shadow:** `integrations/jev_client.py` (type hints, timeout corto, errores explícitos) + en `select_aop` JEV corre **en paralelo** a Haiku (`asyncio.gather`, sin sumar latencia). `Choice` sobre los slugs del catálogo del tenant + AOP previo + últimos 3 mensajes. Haiku sigue decidiendo. Persistir en `intent_classifier_runs` (migración: `jev_slug`, `jev_confidence`, `jev_distribution jsonb`, `jev_latency_ms`) + child run en LangSmith (allowlist, sin PII).
- **B2. Medición:** acuerdo Haiku vs JEV, calibración (confianza vs acierto), coste y latencia. **Prerequisito:** arreglar las fixtures de eval huérfanas (deuda viva) — sin ellas no hay ground truth.
- **B3. Switch:** flag por tenant (`intent_classifier: haiku | jev`), fallback a Haiku si JEV falla o hace timeout; recalibrar umbrales. Como JEV no da razonamiento en texto, la "razón" registrada es la distribución de probabilidades. **ADR nuevo** al hacer el switch.
- **B4. Otros usos (cada uno con su propio shadow, solo después de B3):** filtro de prompt injection en el inbound (`Noul`; es filtro, **no** frontera de seguridad) · routing de modelo en `reason` (Haiku vs Sonnet según complejidad) · score de urgencia/riesgo de escalado · triage de sampling del `slow_agent`. **Descartado:** sustituir el approval L3 o decidir escalados solo con JEV (requieren razón explícita en texto).

### C. Zernio — descubrimiento a fondo antes de diseñar

**Decidido:** WhatsApp vía Zernio es un **canal de entrada**; al escalar se crea un ticket en el helpdesk del cliente (handoff) y la respuesta humana vuelve por WhatsApp vía Zernio. Se respeta la regla "escalados al helpdesk del cliente".
**Kenny:** Zernio va más allá de WhatsApp (abre cuentas Meta Business, conecta ~17 plataformas, MCP con 280+ tools) → hay que mirarlo a fondo, puede aportar más.

- **Ya verificado en su OpenAPI (s76):** webhook `message.received` firmado con HMAC (`X-Zernio-Signature`) · dedupe por `X-Zernio-Event-Id` · responder con `POST /v1/inbox/conversations/{id}/messages` · **templates obligatorios** con la ventana de 24 h cerrada · `profiles` (uno por tenant) y webhooks filtrables por `profileIds` · rate limit WhatsApp ~10 msg/min por destinatario · `thread-control` con Meta Business Agent (evitar dos IAs contestando) · onboarding WhatsApp por API (embedded signup, compra de número + KYC) · inbox unificado de DMs, comentarios y reviews · SDK Python oficial.
- **C0. Spike:** evaluar el catálogo completo (onboarding Meta Business, DMs de IG/FB, comentarios, reviews de Google, MCP, precios) → doc de evaluación + **ADR** con qué adoptamos y qué no.
- **C1. Preguntas a cerrar en el spike:**
  - Handoff bidireccional: humano responde en Zendesk → ¿cómo vuelve a WhatsApp? (webhook del ticket → envío vía Zernio) y cómo se silencia el agente mientras el humano lleva la conversación.
  - Zernio vs WhatsApp nativo del helpdesk (depende de A1): si el helpdesk del piloto ya lo trae, Zernio aporta sobre todo para clientes sin helpdesk y para canales sociales.
  - Una cuenta Zernio de Auyan con un profile por tenant **vs** una cuenta por cliente (facturación, propiedad del número/WABA, offboarding).
  - Aislamiento multi-tenant: mapeo `accountId`/`profileId` → `tenant_id`; credenciales cifradas como el resto.
- **C2. Implementación (después de C0):** `integrations/zernio.py` (`MessageProvider`) + `routers/webhooks_zernio.py` (HMAC + dedupe) + migración del enum `channel_type` + provider en `configure_staging_integrations` + tests.

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
| Bloque 1 | ✅ 1.0–1.9 completados y archivados. |
| Bloque 2 | Motor de billing por resolución mergeado (#234); Stripe pendiente (punto 4 arriba). Duet/Watchtower/Diagnostics sin arrancar. |
| Onboarding | Fase 1 ✅ ([#137](https://github.com/Auyan-ai/platform/pull/137)). Fases 2-4 pendientes — plan en [`onboarding-system-plan.md`](onboarding-system-plan.md); deuda del portal en tabla abajo. |
| Dogfood | **Marea Studio** verificado E2E: tenant `683246c2-10ce-4f6c-a299-5053f32f8c01` (slug `marea-studio`), pedido de pruebas #1181 (`order_id` interno `7133866033432`). Chatwoot de Marea/Purigu sin Teams → no setear `escalation_team_id`. |
| Suite | 1323 tests verde, ruff/mypy limpios (s73). |
| ADRs | Decisiones de arquitectura en [`adr/`](adr/) (formato Nygard). |

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
