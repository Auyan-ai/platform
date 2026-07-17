# Auyan — Estado actual

_Última actualización: 2026-07-17 (limpieza documental: cabeceras s59-s70 y secciones cerradas → [`progress-archive.md`](progress-archive.md); `simulator-design` y `aop-canonical-design` → `docs/archive/`; `architecture-agent-v2.md` compactado. Regla nueva en CLAUDE.md: máximo 3 cabeceras de sesión aquí — la más vieja se archiva al cerrar cada sesión.)_
> _Sesión 72 (2026-06-21) — **Sesión autónoma: 3 PRs MERGEADOS (Zendesk managed-auth, latencia del AOP returns, motor de Billing Bloque 2), suite 1306 verde.** Kenny pidió cerrar los 3 pendientes técnicos dejándole solo Customer Discovery; lo manual quedó en "Arranque sesión 73". [#232](https://github.com/Auyan-ai/platform/pull/232) **Zendesk dual-auth** (API token/Basic, espejo de la s69 de Gorgias) + provider `zendesk` en `configure_staging_integrations`: el enum `channel_type` ya tenía `zendesk` → **sin migración**; el outbound usa el shape estándar (`add_comment` público), **sin** la rareza `source.type`/`body_html` de Gorgias. [#233](https://github.com/Auyan-ai/platform/pull/233) **latencia HOPS por prompt**: el AOP `returns` ahora secuencia "el dato va primero, la afirmación después" (verificar la política en KB/`tenant_facts`/`get_shop_policies` ANTES de afirmar un plazo) → mata de raíz el reject+retry del supervisor; test de invariante en `test_canonical_aops`. [#234](https://github.com/Auyan-ai/platform/pull/234) **motor de Billing Bloque 2** (PRD §7 puntos 1+3): migración `resolution_events` (append-only) + `billing_subscriptions` (snapshot de floor/included/overage, RLS solo-lectura, campos `stripe_*` nullable), conteo por periodo mensual anclado con **ventana de reapertura** (§2.3), catálogo de tiers (números **PROVISIONALES**), `compute_period_usage`, hooks en `respond`/`reopen`, y `GET /billing/usage` + `PUT /billing/subscription`. **Stripe NO entró** (necesita key + dashboard → siguiente trozo aditivo). Suite **1306 verde**, ruff/mypy limpios. **#232/#233/#234 MERGEADOS.** **🔴 Pendiente: aplicar a mano las migraciones de billing (#234) + la del piso L3 (#231) + `add_gorgias_channel` en prod** (Railway no corre SQL). Ver "🚀 Arranque sesión 73" abajo.)_
> _Sesión 71 — **Auditoría de robustez del grafo + cierre del hallazgo 🔴 L3-sin-approval (Opción B, 2 PRs TDD).** Re-auditoría 12-capas: núcleo sólido (`tool_choice` code-gated, `@guarded`, degradación elegante, prompt caching, anti-inyección RAG); el riesgo vive en los bordes. **🔴 Hallazgo:** una L3 destructiva con `is_enabled=True`+`human_approval_required=False` se ejecutaba SIN aprobación humana, confiando solo en el supervisor (sesgado a APROBAR) — el seed de Marea tenía `start_return`/`update_shipping_address` así. **Raíz:** `human_approval_required=False` era ambiguo (opt-out consciente vs default de fábrica), fail-open en schema/función/runtime. **PR1 (piso):** `_l3_requires_human_approval` en `execute_skill` (L3 exige approval salvo opt-out RECONOCIDO) + migración `l3_autonomy_acknowledged_at/_by` (NULL=fail-safe, sin backfill → Marea cae del lado seguro sola) + señal propagada modelo→query→`load_tenant_context`. **PR2 (flexibilidad B):** endpoint rechaza 422 si se desactiva el approval de una L3 sin `acknowledge_l3_autonomy=true`; `upsert` sella/limpia el acknowledgment. **1297 tests verde, ruff limpio.** **PENDIENTE BLOQUEANTE: aplicar la migración a staging a mano ANTES del deploy** (Railway no corre SQL → si no, `load_tenant_context` hace SELECT de columnas inexistentes y escala todos los turnos). **Backlog de la auditoría:** #2 race de concurrencia (sin lock por conversación; la idempotencia es por `message_id`, no serializa 2 mensajes distintos), #3 entrega outbound best-effort tras marcar resuelto/cerrar ticket. Ver "🚀 Arranque sesión 73" abajo.)_

> Historial completo en [`docs/progress-archive.md`](progress-archive.md). Contexto estratégico en [`docs/auyan-master-context.md`](auyan-master-context.md).

---

## 🚀 Empezar aquí — pendientes priorizados

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
| Suite | 1306 tests verde, ruff/mypy limpios (s72). |

---

## 🧭 Foco estratégico — Customer Discovery

Regla dura (sesión 53, vigente): **el outreach manda**; no construir features nuevas sin conversaciones de discovery. Outreach activo desde julio 2026. Bifurcado en 2 cohortes según [`market-analysis-2026-06.md`](market-analysis-2026-06.md): 5 e-commerce escenario 4 (quemados de Gorgias/Permut/GuruSup) + 5 comercializadoras de energía independientes (driver Ley 10/2025, deadline 28-dic-2026). NO pivotar; el dato decide. Plan operativo completo (ICP, mensajes, formulario): [`customer-discovery.md`](customer-discovery.md).

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
| Shopify test store | ✅ Órdenes reales `auyan-e2e` en Lunaria (#1001-#1003) y Marea (#1181). |
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
- [`market-analysis-2026-06.md`](market-analysis-2026-06.md) — análisis de mercado, cohortes, Ley 10/2025.
- [`billing-manual.md`](billing-manual.md) — pricing/tiers + runbook de cobro manual.
- [`billing-resolution-prd.md`](billing-resolution-prd.md) — PRD del billing por resolución.
- [`onboarding-system-plan.md`](onboarding-system-plan.md) — plan del onboarding (Fases 1-4).

**Históricos (nunca fuente de verdad — ver convención en CLAUDE.md):**
- [`progress-archive.md`](progress-archive.md) — historial de sesiones, sprints y secciones compactadas.
- [`archive/simulator-design.md`](archive/simulator-design.md) — diseño del simulator (implementado en 0.10).
- [`archive/aop-canonical-design.md`](archive/aop-canonical-design.md) — diseño de los AOPs canónicos (fuente real: `apps/api/aops/canonical.py`).
