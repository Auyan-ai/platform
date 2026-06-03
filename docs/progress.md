# Auyan — Estado actual

_Última actualización: 2026-06-03 (sesión 62 — **Dogfood L3 cerrado E2E + 6 fixes**. Cerrado el flujo L3 con approval de punta a punta vía **widget Chatwoot real** (`order_change` → `update_shipping_address` sobre #1181: gate → `pending_approval` → aprobación en dashboard → ejecución real en Shopify → confirmación al cliente → revert a la dirección original). El camino de aprobación estaba **roto de raíz**; el dogfood destapó 5 bugs + 1 de seguridad, todos con PR + tests: [#172](https://github.com/Auyan-ai/platform/pull/172) **H5** colisión `account_id` cross-tenant (índice único parcial + guard fail-closed); [#173](https://github.com/Auyan-ai/platform/pull/173) 500 al aprobar (SkillContext con kwargs obsoletos → helper `build_commerce_integration_ctx`); [#174](https://github.com/Auyan-ai/platform/pull/174) **B1** el dashboard interno no exigía `super_admin` (un `tenant_admin` podía entrar — no era fuga de datos, la API aísla, pero sí frontera de operador rota); [#175](https://github.com/Auyan-ai/platform/pull/175) 500 mensaje `agent_human` sin autor (constraint); [#176](https://github.com/Auyan-ai/platform/pull/176) 422 país en texto libre ("España") → `country_code` ISO; [#177](https://github.com/Auyan-ai/platform/pull/177) mensaje al cliente crudo → redactado con **Haiku** (fallback plantilla); [#178](https://github.com/Auyan-ai/platform/pull/178) **entrega al helpdesk** de los mensajes del flujo L3 (escalate + approve) — **ABIERTO**, resto MERGEADOS. `complaint` también verificado (empatía + escalar, sin L3). **Decisión de producto:** ambos roles aprueban L3, cada uno desde su dashboard (la API ya aísla por tenant). Pendiente: **país determinista** (hoy lo rellena el LLM), H4, H6. Ver "Dogfood E2E Marea" abajo._
> _Sesión 61 — **Fix de raíz Hallazgo 1 (provisioning)**: `provision_tenant` ahora crea `tenant_configurations` + prompt base `system` (helper idempotente `ensure_tenant_config_and_prompt` + script de backfill). [PR #171](https://github.com/Auyan-ai/platform/pull/171) MERGEADO._
> _Sesión 60 — **Fix #5 intent-switch continuity-aware** ([#167](https://github.com/Auyan-ai/platform/pull/167) MERGEADO, cierra 5/5 fixes de grafo) + **dogfood E2E sobre Marea** (Fix #5 multi-turno + order_status #1181 + returns/refunds + **Chatwoot real**) → destapó hallazgos #168 (política KB/facts) y #169 (token Shopify en claro), MERGEADOS._
> _Sesión 59 — **AOPs canónicos + fixes de grafo**. (1) Diseñados y verificados uno a uno los 8 AOPs por defecto de e-commerce ES en [`docs/aop-canonical-design.md`](aop-canonical-design.md). (2) **PR #1 [#163](https://github.com/Auyan-ai/platform/pull/163) MERGEADO**: provisioning copy-on-create — cada tenant nace con sus 8 AOPs + permisos (L1/L2 auto, L3 con approval) vía hook en `provision_tenant`; `aops/canonical.py` es la fuente de verdad + `scripts/seed_canonical_aops.py` para backfill. (3) Fixes de grafo (PR #2): [#164](https://github.com/Auyan-ai/platform/pull/164) (cablear `confidence_threshold` + `require_supervision` por-AOP, antes muertos; guard anti prompt-injection) y [#165](https://github.com/Auyan-ai/platform/pull/165) (fecha/hora TZ-aware del tenant + dep `tzdata`) — **AMBOS ABIERTOS, esperan review/merge**. (4) **Backfill aplicado en staging**: Marea Studio (8 nuevos) y Lunaria (6 nuevos + returns/default actualizados a canónico, `consulta_envio` viejo desactivado) — los 8 canónicos activos + 11 permisos en ambos. PENDIENTE: **Fix #5 intent-switch en sesión nueva** — ver sección abajo)._

> Historial completo en [`docs/progress-archive.md`](progress-archive.md). Contexto estratégico en [`docs/auyan-master-context.md`](auyan-master-context.md).

---

## ✅ Fix #5 intent-switch continuity-aware — HECHO (sesión 60)

**Rama:** `fix/intent-switch-continuity` (desde `develop`, con #164 + #165 ya mergeados). **Modelo:** Opus.

**El problema (verificado en sesión 59):** el grafo NO usa checkpointer y `process_inbound` arma el state desde cero cada mensaje → `aop_slug` nacía vacío → el clasificador corría cada turno pero **CIEGO**. Riesgo: flapping mid-procedimiento en respuestas cortas/ambiguas ("el azul", "12345").

**El fix aplicado:**
1. `select_aop` carga el AOP previo desde `intent_classifier_runs` con `get_last_intent_for_conversation` (ya existía; sin migración ni checkpointer).
2. Lo inyecta en el prompt del clasificador → **continuidad a nivel LLM** (juzga si el pivote tiene sentido y devuelve conf alta cuando sí).
3. **Histéresis determinista** en `_resolve_aop_slug` (red de seguridad): continuidad (mismo slug) / salir-de-`default`-fácil (basta `min_confidence`) / pivote-confiable (≥ `intent_switch_threshold=0.70`, setting nuevo) / si nada aplica → mantiene el previo (anti-flapping).
4. Borrado el scaffolding muerto (`_should_reclassify`, `aop_locked_until_turn`, `aop_completed_signal`). `was_reclassification` ahora se infiere de DB.
5. Desambiguación por pregunta: **diferida** (la continuidad ya hace seguro el split returns/refunds). `pending_intent` se conserva como reservado.

**Edge cases cubiertos:** AOP previo desactivado a mitad de conversación → se trata como primer turno; slug inválido con conf alta + hay previo → mantiene el previo (no salta a default).

**Verificación:** suite **1143 verde** (matriz pura de histéresis de 10 casos + integración), ruff clean, 0 mypy nuevos.

**Esto cierra los 5/5 fixes de grafo del 10/10.** Diseño completo en `docs/aop-canonical-design.md`.

**Diferido** (capa opcional del fix de fecha #4): `days_since_order` calculado en código para que el LLM no reste fechas.

**Próximo paso técnico:** mergear este PR → con los 8 AOPs canónicos + 5/5 fixes de grafo listos, queda desbloqueado el dogfood E2E con la "tienda ligera" de Lunaria (correr la 25/25 con judge — ver Bloque 0.11).

---

## 🐕 Dogfood E2E Marea — L1 + L3 verificados ✅ (sesiones 60→62)

Target del dogfood: **Marea Studio** (`683246c2-10ce-4f6c-a299-5053f32f8c01`, slug `marea-studio`) — completa (KB 8 chunks+embeddings, facts, 8 AOPs canónicos, Shopify + Chatwoot, 11 tool permissions). Pedido real de pruebas: **#1181** (`order_id` interno `7133866033432`).

**✅ L1 / routing (sesión 60):** Fix #5 multi-turno (shipping→returns→refunds, continuity-aware sin flapping); `order_status` sobre #1181 (L1 success, sin invención); returns/refunds responden política sin escalar; **Chatwoot real E2E** (widget → `/webhooks/chatwoot` → marea-studio → skill → respuesta en el widget).

**✅ L3 con approval (sesión 62) — cerrado E2E:** `order_change` → `update_shipping_address` sobre #1181, vía **widget Chatwoot real**. Cadena completa: gate (no ejecuta, crea `pending_approval`, avisa al cliente) → aprobación desde dashboard → **ejecución real contra Shopify** → confirmación natural al cliente → **revert** a la dirección original. `complaint` también verificado (empatía + recoge contexto + escala con razón, sin L3, sin promesas). El camino de aprobación **nunca había funcionado**; lo abrió este dogfood.

### Hallazgos del dogfood

| # | Hallazgo | Estado |
|---|---|---|
| H1 | Provisioning no crea `tenant_configurations` ni prompt base → tenant nuevo falla 1er mensaje | ✅ [#171](https://github.com/Auyan-ai/platform/pull/171) |
| H2 | Política anclada solo en `get_shop_policies` (returns/refunds escalaban) | ✅ [#168](https://github.com/Auyan-ai/platform/pull/168) |
| H3 | access_token Shopify cacheado en claro en DB | ✅ [#169](https://github.com/Auyan-ai/platform/pull/169) |
| H4 | `returns` calcula plazo desde `created_at`, no desde la recepción (más estricto que la política) | ⏳ chip |
| H5 | Colisión `account_id` cross-tenant en webhook (`LIMIT 1` sin unicidad) | ✅ [#172](https://github.com/Auyan-ai/platform/pull/172) — índice único parcial + fail-closed |
| H6 | Cierre por inactividad no sincroniza `resolved` al helpdesk + verificar entrega del nudge | ⏳ chip |

### Bugs del flujo L3 (sesión 62 — el approve estaba roto de raíz)

| Bug | Qué | PR |
|---|---|---|
| A | 500 al aprobar: `SkillContext` con kwargs obsoletos (`shopify_domain/token`) → `TypeError`. Helper `services/commerce_context.build_commerce_integration_ctx` (creds de `tenant_integrations` + token exchange) | ✅ [#173](https://github.com/Auyan-ai/platform/pull/173) |
| B1 | El dashboard interno (`(dashboard)/layout.tsx`) solo validaba sesión, no `super_admin` → un `tenant_admin` podía renderizarlo. **No** es fuga de datos (la API aísla: `get_tenant_id` da 403), pero sí frontera de operador rota | ✅ [#174](https://github.com/Auyan-ai/platform/pull/174) |
| B | 500: mensaje `agent_human` sin `author_user_id` (viola `messages_human_has_author`), en approve **y** reject | ✅ [#175](https://github.com/Auyan-ai/platform/pull/175) |
| C | 422 Shopify: `country` en texto libre ("España") no soportado → `country_code` ISO (`_country_to_iso2`, ES-first + fallback) | ✅ [#176](https://github.com/Auyan-ai/platform/pull/176) |
| D | Mensaje al cliente = volcado crudo del output (slug + dict) → redactado con **Haiku** (`services/approval_reply`, fallback plantilla) | ✅ [#177](https://github.com/Auyan-ai/platform/pull/177) |
| E | Los mensajes del flujo L3 (escalate "en revisión" + confirmación al aprobar) **no llegaban al cliente** en el widget. E1: webhooks solo entregaban en `respond`. E2: approve/reject no despachaban al helpdesk (`services/helpdesk_delivery`) | ⏳ [#178](https://github.com/Auyan-ai/platform/pull/178) ABIERTO |

**Decisión de producto (quién aprueba L3):** ambos roles, cada uno desde su dashboard — `tenant_admin` los suyos vía `/clients`, `super_admin` vía el dashboard interno. La API ya aísla por tenant, así que **no** se añade `require_role` al router de approvals. (Auto-graduación de skills a automático y self-service de AOPs = roadmap.)

**Operativo:** página de prueba del widget en `apps/api/scripts/chatwoot_widget_test.html` (websiteToken de Purigu; **sin commitear**). Servirla con `python3 -m http.server 8899 --directory apps/api/scripts` → `http://localhost:8899/chatwoot_widget_test.html`.

### 🌅 Arranque (sesión 63)
- **Modelo:** Sonnet para los chips acotados; Opus si toca diseño (país determinista / observabilidad).
- **Verificar primero:** mergear **#178** → forzar deploy de `platform` si no firea (ver [[reference_railway_deploy_trigger]]) → re-probar L3 desde el widget: deben llegar el "en revisión" y la confirmación de Haiku.
- **Chips pendientes (por prioridad sugerida):**
  1. **País determinista** — hoy el LLM rellena `country` (puso "Spain" solo); para tienda solo-España no debe depender del LLM. Opción A: preservar el país del pedido actual; opción B: default del tenant. Importante porque clientes reales omiten el país.
  2. **H4** — plazo de devolución desde la recepción, no `created_at` (+ dato en facts).
  3. **H6** — sync de cierre por inactividad → helpdesk + entrega del nudge (relacionado con #178/E2).
  4. **Observabilidad:** la ejecución del L3 al aprobar no deja fila en `skill_audit_log` (solo queda el gate como `rejected_by_permissions`).
  5. **PII:** la dirección de envío no se redacta en `pending_approvals.inputs_redacted`.
  6. **Limpieza:** dead code `isDashboardRoute` en `middleware.ts`; retrofitear `load_tenant_context` al helper `build_commerce_integration_ctx`; `REPLY_MODEL` (Haiku) constante → promover a setting + multi-idioma en `approval_reply`.
  7. Re-seed `--update` de AOPs canónicos a **Lunaria** (pendiente del #168).

---

## Empezar aquí

**Modelo recomendado:** Sonnet.

**Rama actual esperada:** `develop`.

**Estado general:**

| Área | Estado |
|---|---|
| Bloque 0 | 0.1–0.10 completados. 0.11 reencuadrado como Agent Verification Staging. |
| Bloque 1 | 1.0–1.9 completados y archivados. 1.10 billing manual tiene runbook, pero depende de inputs externos por cliente. |
| Staging DB | Migraciones de Bloque 1 aplicadas; ya no bloquean la validación. |
| Siguiente paso | **Customer Discovery** sigue como foco estratégico (sesión paralela). En el track técnico: validar magic link visual de Fase 1 (espera rate limit + fix Site URL) → arrancar **Fase 2** del onboarding (portal del cliente con doc upload + Shopify token paste + helpdesk OAuth). Corrida simulator 25/25 queda relegada. |
| Reciente en develop | #131 recalibró pricing, #132 agent skills, #133 Chatwoot HMAC + simulator reseed, #134/#135 docs, #136 guardrail anti-invención, **#137 provisioning productizado (Fase 1)**. |
| Sistema de onboarding | Plan completo cerrado vía /grill-me: ver `docs/onboarding-system-plan.md`. Fase 1 ✅ mergeada (provisioning + magic link + UI). Fases 2-4 pendientes (portal cliente, Shopify content import + starter AOPs, lifecycle gates). |
| Chatwoot staging | ✅ Integración real registrada en Lunaria (cuenta `Purigu`, `account_id 167723`) + webhook → `/webhooks/chatwoot`. ✅ **Smoke test e2e PASÓ** (conv `99386d3b`): consulta de pedido #1003 resuelta con skill Shopify L1 sobre datos reales, traza en LangSmith. |

---

## Foco actual — Customer Discovery (sesión 53)

**Diagnóstico:** ~75k líneas, ~90% del stack, **0 clientes reales** entrevistados. Lunaria es simulador, no cliente. La ansiedad por la competencia (Sierra, Decagon, Permut, GuruSup, ElevenLabs) es síntoma: el diferenciador de Auyan no es la calidad del agente (table-stakes en 2026), es la **operación gestionada** del agente para el segmento.

**Regla dura:** no tocar el agente hasta mandar 3 mensajes de descubrimiento. Interés ≠ demanda.

**Objetivo de la semana:** 10 marcas ICP → 3 mensajes → 3 conversaciones.

**ICP Starter:** Shopify España, 2,5–5 M€ facturación, 500–1.000 tickets/mes, ≥1 persona cuyo trabajo sea CX (filtro duro). Dos cohortes a partes iguales — **ya-usa-bot** (Gorgias AI / Tidio / Intercom Fin / Zendesk AI) vs **no-bot**; el contraste ES el mapa de mercado.

Plan completo en [`docs/customer-discovery.md`](customer-discovery.md): reencuadre, mensaje de outreach verbatim, formulario de 9 preguntas, e hipótesis testeables de pricing / wedge / GTM.

**En marcha (otro chat):** construir `docs/discovery-targets.md` con 10 marcas reales (no inventar datos) usando herramientas €0 (Store Leads, Wappalyzer, view-source, Trustpilot, LinkedIn).

**Seguridad:** repo `Auyan-ai/platform` ahora **privado** (antes público con docs de estrategia expuestos, 0 forks). `.gitignore` no borra historia ya commiteada — privado es el fix limpio.

---

## Sistema de onboarding productizado — Fase 1 cerrada

**Plan completo:** [`docs/onboarding-system-plan.md`](onboarding-system-plan.md) (cerrado vía /grill-me sesión 56). Modelo: managed por invitación (no signup público), 4 fases, dogfood en tienda Shopify real (Marea Studio).

**Fase 1 — Provisioning (mergeado [PR #137](https://github.com/Auyan-ai/platform/pull/137)):**

- Migración `plan_tier` (`founding`/`standard`/`trial`) — semilla para futuro tier trial diferido.
- Service `tenant_provisioning` que usa `supabase_service_role_key` (antes sin uso) → invite vía Supabase Admin + crea `tenants` + `public.users` + `tenant_onboarding` + `tenant_assignment` en transacción + lifecycle `initial→discovery`.
- Endpoint `POST /tenants` (super_admin only) + UI "Nuevo cliente" en dashboard (botón en `ReviewQueueHome`).
- 11 tests nuevos (5 service + 6 endpoint). 865 tests pasan, sin regresiones.
- Verificado en staging: tenant **Marea Studio** (`marea-studio`) creado desde la UI, lifecycle `discovery`, invite generado con JWT real. Plumbing funciona.

**Pendiente Fase 1 (mañana, 2026-06-01):**

1. Fix **Supabase staging Site URL** = `https://auyan-web-staging.up.railway.app` + Redirect URLs.
2. Esperar 1h por rate limit del built-in email Supabase (~4/h).
3. "Send magic link" desde Authentication → Users → kennyrmv@gmail.com.
4. Validar visualmente: click → portal de onboarding del tenant Marea Studio carga bien.

**Próximas fases (planificadas):**

- **Fase 2:** portal del cliente — wizard extendido con doc upload (reuso `pending_review`), Shopify token paste, Chatwoot token + auto-webhook, OAuth buttons Gorgias/Zendesk. Lifecycle auto `discovery→building` por checklist.
- **Fase 3:** Shopify content auto-import (pages/blogs/articles → markdown → `pending_review`) + starter pack AOPs e-commerce ES clonado al provisionar.
- **Fase 4:** dogfood end-to-end completo en Marea Studio + simulator 25/25.

---

## Bloque 1 — Sprint A en progreso

### Completado y archivado

| Sub-PR | Foco | Estado |
|---|---|---|
| 1.0 | Design Sprint + shell Mercury light | ✅ Archivado |
| 1.1 | `tenant_playbook` | ✅ Archivado |
| 1.2 | `tenant_facts` | ✅ Archivado |
| 1.3 | Onboarding wizard + lifecycle | ✅ [PR #102](https://github.com/Auyan-ai/platform/pull/102), QA manual aprobado |
| 1.4 | KB drop-zone + pending review | ✅ Archivado |
| 1.5 | Reporte semanal + aprobación + Postmark + cron | ✅ [PR #104](https://github.com/Auyan-ai/platform/pull/104)–[#107](https://github.com/Auyan-ai/platform/pull/107) |
| 1.6 | Dashboard cliente 7 secciones MVP | ✅ [PR #109](https://github.com/Auyan-ai/platform/pull/109)–[#113](https://github.com/Auyan-ai/platform/pull/113) |
| 1.7 | Review Queue interna cross-tenant | ✅ [PR #115](https://github.com/Auyan-ai/platform/pull/115) |
| 1.8 | Landing pública `apps/landing` + Plausible | ✅ [PR #117](https://github.com/Auyan-ai/platform/pull/117) |
| 1.9 | Email outbound general: templates + queue + retry + UI | ✅ [PR #119](https://github.com/Auyan-ai/platform/pull/119)–[#121](https://github.com/Auyan-ai/platform/pull/121) |

### Sub-PR 1.10 — Billing manual primeros clientes

**Objetivo:** cerrar operación manual de cobro para los primeros 1–2 clientes antes de abrir Stripe/Billing técnico en Bloque 2.

Estado: runbook creado; bloqueado por inputs externos por cliente. No es el foco activo mientras se prioriza la verificación del agente.

Runbook base:

- [`docs/billing-manual.md`](billing-manual.md) — política Founding Partner, tiers, checklist por cliente y flujo factura + transferencia.

Faltan inputs externos por cliente:

1. Definir precio final acordado por cliente y responsable comercial.
2. Confirmar datos fiscales y destinatario de facturación.
3. Confirmar contacto operativo y fecha de inicio de servicio.
4. Registrar factura manual enviada y estado de cobro fuera del producto.

### Nota viva — Shopify content import / KB bootstrap

Idea recomendada para reducir fricción de onboarding: importar contenido existente de Shopify al pipeline de KB.

Investigación inicial con docs oficiales Shopify:

- Shopify Admin API expone pages/blogs/articles con HTML de contenido estático.
- Puede detectar páginas relevantes: `faq`, `devoluciones`, `envíos`, `garantía`, `contacto`, `privacy`, `terms`.
- No reemplaza el drop-zone: muchas FAQs viven en theme, apps, metafields/metaobjects o páginas externas.

Spike sugerido:

1. Listar pages/blogs/articles.
2. Detectar títulos relevantes.
3. Convertir HTML a texto/markdown.
4. Mostrar preview en cola `pending_review`.

---

## Pendientes vivos

### Deuda — Onboarding portal (Fase 2)

| Deuda | Severidad | Notas |
|---|---|---|
| Step 7 (Legal) pide aceptar DPA + Términos + GDPR sin links a documentos reales | media | El cliente acepta cláusulas que no puede leer. Bloquea cumplimiento real. Crear `apps/web/app/(public)/legal/{dpa,terms,privacy}/page.tsx` con contenido legal + linkearlos desde los checkboxes del step. |
| Step 9 (Confirmación) deuda: si el lifecycle no avanza a `building` al darle "Enviar", el cliente queda atascado sin saber qué falta | media | El portal debe mostrar el checklist remanente con CTAs a cada step incompleto. Hoy parpadea y no redirige porque el server-side layout vuelve a mandar a `/onboarding`. (Resuelto en PR #147.) |
| Step 6 (KB) solo acepta texto pegado o URL | **alta** | Cliente real tiene FAQs en PDF, políticas en Word, screenshots de procesos, hojas Excel, notas en `.md`. Hoy debe copy-paste manual. Implementar upload de: PDF, DOCX, DOC, TXT, MD, RTF, PNG/JPG/WebP (vision para extracción), XLSX/CSV (tablas). Pipeline: upload a Supabase Storage → worker extrae texto (Anthropic Files API o textract según tipo) → crea `tenant_knowledge_submission` con `original_filename` + `metadata.extracted_from` → flujo de aprobación normal. Cap por archivo (10 MB) + total por tenant (configurable). |
| Imágenes laterales KREA pendientes (steps 4, 5, 6, 8) | baja | Mientras tanto se ve un placeholder dashed. No bloquea funcionalidad. Prompts ya documentados en gstack/designs/. |

### Bloque 0.11 — Agent Verification Staging

Objetivo: verificar que el agente funciona correctamente en condiciones cercanas a vida real, sin depender de datos inventados y con LangSmith como fuente primaria de observabilidad.

Alcance reencuadrado:

1. Integrar LangSmith en staging para trazas de conversación, grafo, nodos, decisiones, skills, coste y errores.
2. Optimizar simulator: Sonnet como judge default, Opus opcional, corrida normal con tope de coste de `$5`.
3. Crear fixture realista de tenant: playbook, facts, onboarding, KB, AOPs, tool permissions e integraciones.
4. Preparar Shopify test store con órdenes reales marcadas `auyan-e2e`; no aceptar verificación formal sobre datos inventados.
5. Probar primero `/webhooks/inbound` y luego Chatwoot real como primer helpdesk.
6. Medir alineación entre propuesta del agente y decisión humana para decidir cuándo una skill puede pasar a automático por tenant.

Criterios de aceptación iniciales:

- 25/25 scenarios pasan critical assertions sin judge.
- Sample con judge Sonnet obtiene promedio mínimo `8/10`.
- 0 acciones L3 ejecutadas sin aprobación.
- 0 tracking/refunds/orders inventados.
- Corrida normal bajo `$5`.
- 100% de runs visibles en LangSmith con correlación a DB.

Tenant de prueba Lunaria staging: `11111111-1111-1111-1111-111111111111`.

Resultado corrida 25/25 + fix anti-invención (sesión actual):

- **Fase A (sin judge, 25/25):** ✅ todas las assertions críticas pasan. Criterio #1 cumplido.
- **Fase B (judge Sonnet):** promedio `7.28/10` — **bajo el `≥8.0`** del criterio #2. Coste `$1.3936` (bajo `$5`, criterio #5 ✅). EX-01 con WARNING es intencional (mock error). 0 L3 sin approval (#3 ✅), 0 tracking/refunds inventados (#4 ✅), 100% en LangSmith correlacionado a DB (#6 ✅).
- **Hallazgo raíz del 7.28:** con KB vacía y AOPs sin verificar, el agente **alucinaba datos blandos sin respaldo** — DE-01 inventaba un plazo de envío; RE-02/RE-07 inferían política de devolución cuando `get_shop_policies` devolvía vacío. Es un problema de **comportamiento/guardrail**, separable del **contenido** (KB/AOPs reales), que se difiere al onboarding del primer cliente.
- **Fix aplicado (`aops/compiler.py`):** reforzado `_render_global_rules` — la **única** regla anti-invención incondicional del system prompt (el bloque de KB sólo aparece si hay chunks). Ahora prohíbe afirmar plazos/fechas/políticas/importes sin respaldo y manda tratar tool vacío/error como dato no disponible. Test nuevo en `tests/test_aop_compiler.py`; suite del compiler **63/63 verde**.
- **Verificación barata (3 escenarios, judge Sonnet, ~`$0.13`):** el fix **cambia el comportamiento**. DE-01 dejó de inventar y ahora **escala honestamente** (la assertion `response_contains.días` ahora falla = ya no inventa; judge `4.2→3.0` porque el judge premia dar respuesta y castiga la honestidad cuando no hay contenido). RE-02 estable (`6.8`; el "30 días" viene del AOP, no inventado → 3/3 assertions pasan). RE-07 `8.0→8.2`.
- **Lectura:** el guardrail es **quirúrgico** — suprime lo no respaldado (DE-01) pero no lo respaldado por el AOP (RE-02 sigue diciendo "30 días"). El **judge no puede validar guardrails sobre KB vacía** porque mide contenido, no comportamiento. **Criterio #2 (judge ≥8) queda bloqueado por CONTENIDO real** (KB + AOPs verificados en onboarding), no por comportamiento. Guardrails anti-alucinación: **listos para el primer cliente**.
- **Estado: ⏳ esperando la "tienda ligera" de Lunaria para correr la última prueba 25/25 con judge.** El fix anti-invención sale en PR aparte contra `develop`. La tienda ligera (la arma Kenny) = contenido mínimo en DB que los 25 scenarios ya asumen, **sin** tocar el grafo:
  - **`tenant_facts`:** `return_window_days: 30`, `shipping_info` (estándar 3-5 días hábiles · express 1-2 · gratis > $50), `business_hours`, `support_email`/`support_phone`/`website_url` (para escalar con contexto honesto).
  - **KB (`knowledge_base_chunks` con embeddings, vía `seed_kb`):** doc de **envíos** (DE-01, CE-02/05), doc de **devoluciones** (30 días + digital no retornable; RE-01/02/05), doc de **garantía** (DE-02 — *hoy no está en ningún mock, el agente no tiene de dónde sacarlo*). **Dejar sin documentar a propósito** los temas que prueban escalar-cuando-no-sé (EX-02 cambio de color, DE-03 fuera de alcance): si se documentan, esos scenarios dejan de escalar y rompen su assertion.
  - **3 AOPs a verificar/redactar** (los scenarios fuerzan estos slugs): `consulta_envio` (CE-*, EX-01/03), `returns` (RE-*), `default` (DE-*, EX-02/04) — cada uno con allowed_skills correctos, procedimiento por caso, guardrails y escalation_triggers.
  - **Ya OK (no crear):** datos de pedido/tracking/producto/refund vienen de **mocks por scenario**; integración Shopify registrada; tiers `refund_partial`/`cancel_order` = L3.

Estado LangSmith staging:

- ✅ [PR #127](https://github.com/Auyan-ai/platform/pull/127): LangSmith como observabilidad primaria del agente; Langfuse queda como espejo opcional.
- ✅ [PR #128](https://github.com/Auyan-ai/platform/pull/128): `LANGSMITH_WORKSPACE_ID`, endpoint EU, `trace_id/dotted_order` y child `agent_model_call` tipo `llm` para tokens/coste nativos.
- ✅ Railway staging configurado con `LANGSMITH_ENDPOINT=https://eu.api.smith.langchain.com`, workspace `bd943bb5-40a8-4178-a15c-71d473fca472` y proyecto `auyan-staging`.
- ✅ Webhooks reales validados en LangSmith: `agent_conversation` muestra input/output/decisión/confianza; `agent_model_call` muestra `input_tokens`, `output_tokens`, `total_tokens` y `total_cost`.

Pendiente futuro, sólo cuando haga falta más granularidad:

- Crear sub-runs internos por paso del grafo: `load_tenant_context`, `select_aop`, `retrieve_knowledge`, `reason`, `supervise`, `execute_skill`, `respond`/`escalate`.
- Enriquecer cada sub-run con AOP seleccionado, chunks recuperados, tool calls, approvals y errores, manteniendo cuidado de no exponer secretos ni PII innecesaria.

### Staging / servicios externos

| Pendiente | Estado |
|---|---|
| LangSmith | ✅ Validado en staging EU: traces reales en `auyan-staging`, root `agent_conversation` + child `agent_model_call` con tokens/coste nativos. Sub-runs internos por nodo quedan como mejora futura. |
| Simulator | Optimizado: Sonnet judge por defecto, Opus opcional, cap `$5/día` por tenant. #133 añadió reseed de user profiles y modo sin-judge en `_compute_status`. ✅ Corrida 25/25 contra Lunaria ejecutada: Fase A 25/25 críticas; Fase B judge `7.28/10` (bajo `≥8.0` por KB vacía, no por comportamiento — ver subsección 0.11). |
| Shopify test store | ✅ Tres órdenes reales `auyan-e2e` creadas en Lunaria: `#1001` (`CE-NO-TRACKING`, sin tracking), `#1002` (`CE-TRACKING`, tracking `1Z999AA10123456784`) y `#1003` (`RETURNS-IN-WINDOW`, tracking `1Z999AA10123456785`). ✅ Shopify registrado como integración primaria `commerce/shopify` en `tenant_integrations` con credentials cifradas. |
| Chatwoot Cloud | ✅ **Smoke test e2e PASÓ** (conv `99386d3b`, 2026-05-30). Cadena verificada: widget → webhook `200` → HMAC de #133 validada contra Chatwoot real → AOP `consulta_envio` → `shopify.get_order_status` (L1, success, 493ms) sobre el pedido real #1003 → respuesta en Chatwoot + dashboard → 4 runs `agent_conversation` en LangSmith con tokens/coste, correlacionadas a Supabase por tags `tenant`/`channel:chatwoot`. Integración registrada vía `configure_staging_integrations.py` (cuenta `Purigu`, `account_id 167723`). ⚠️ **Gota operativa:** las credenciales deben cifrarse con la `INTEGRATIONS_SECRET_KEY` de staging — registrar siempre vía `railway run ... configure_staging_integrations`, no en local (si no → `InvalidTag`/500 al desencriptar en el server). |
| Gorgias OAuth app | Sigue pendiente; se implementará después de Chatwoot. |
| Zendesk OAuth app | Sigue pendiente; se implementará después de Chatwoot. |
| Postmark | Falta `POSTMARK_API_TOKEN`, `POSTMARK_FROM_EMAIL` y **dominio `auyan.ai` aún no comprado** → DKIM/SPF bloqueado. Workaround Sender Signature con single email se descartó por estética (invite saliendo desde `kennyrmv@gmail.com`). Esperar a tener dominio para hacer setup completo + plug como SMTP de Supabase (saca rate limit del built-in). |
| Supabase Auth staging | Pendiente: **Site URL** = `https://auyan-web-staging.up.railway.app` (hoy apunta a `localhost:3000`, rompe magic links). + añadir a Redirect URLs. Bloquea validación visual del magic link de Fase 1. |
| Weekly Reports cron | Falta setear `DATABASE_URL` en GitHub Actions para el workflow programado. |

---

## Referencias rápidas

- [`docs/progress-archive.md`](progress-archive.md) — historial completo.
- [`docs/customer-discovery.md`](customer-discovery.md) — plan de descubrimiento de clientes (sesión 53).
- [`docs/billing-manual.md`](billing-manual.md) — pricing, tiers, ICP y billing manual.
- [`docs/auyan-master-context.md`](auyan-master-context.md) — fuente única de verdad negocio + producto.
- [`docs/architecture-agent-v2.md`](architecture-agent-v2.md) — arquitectura técnica del agente.
- [`docs/architecture-web.md`](architecture-web.md) — arquitectura dashboard web.
- [`docs/DESIGN.md`](DESIGN.md) — sistema visual vigente.
- `CLAUDE.md` — reglas operativas del proyecto.
