# Auyan — Estado actual

_Última actualización: 2026-05-31 (sesión 56 — **Fase 1 del sistema de onboarding productizado** mergeada vía [PR #137](https://github.com/Auyan-ai/platform/pull/137). Plan completo end-to-end cerrado vía /grill-me en `docs/onboarding-system-plan.md`. Provisioning verificado en staging: tenant **Marea Studio** creado desde la UI nueva "Nuevo cliente", lifecycle `initial→discovery`, invite generado con JWT válido. Magic link en sí queda **pendiente de validación visual** porque (a) Supabase staging tenía Site URL=`localhost:3000` y mandó el redirect al vacío, y (b) tras consumir el primer link, se golpeó el rate limit del built-in email de Supabase — reintentar mañana tras esperar 1h y arreglar Site URL. Customer Discovery sigue siendo el foco estratégico paralelo)._

> Historial completo en [`docs/progress-archive.md`](progress-archive.md). Contexto estratégico en [`docs/auyan-master-context.md`](auyan-master-context.md).

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
| Simulator | Optimizado: Sonnet judge por defecto, Opus opcional, cap `$5/día` por tenant. #133 añadió reseed de user profiles y modo sin-judge en `_compute_status`. Falta la corrida real 25/25 contra Lunaria staging. |
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
