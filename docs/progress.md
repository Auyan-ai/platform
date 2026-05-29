# Auyan — Estado actual

_Última actualización: 2026-05-29 (sesión 52 — 0.11A LangSmith staging validado en EU: traces reales, workspace correcto y tokens/coste nativos; siguiente foco fixture Shopify/Chatwoot)._

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
| Siguiente paso | 0.11A — avanzar fixture Shopify realista y Chatwoot sandbox; LangSmith staging ya validado. |

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
| Simulator | Código base optimizado: Sonnet judge por defecto, Opus opcional y cap normal de `$5/día` por tenant. Falta corrida real 25/25 contra tenant Lunaria staging. |
| Shopify test store | ✅ Tres órdenes reales `auyan-e2e` creadas en Lunaria: `#1001` (`CE-NO-TRACKING`, sin tracking), `#1002` (`CE-TRACKING`, tracking `1Z999AA10123456784`) y `#1003` (`RETURNS-IN-WINDOW`, tracking `1Z999AA10123456785`). ✅ Shopify registrado como integración primaria `commerce/shopify` en `tenant_integrations` con credentials cifradas. |
| Chatwoot sandbox | En progreso: script `configure_staging_integrations.py` valida account/token y registra la integración Chatwoot cifrada en `tenant_integrations`. Falta crear cuenta/inbox/webhook/token reales y ejecutar contra staging. |
| Gorgias OAuth app | Sigue pendiente; se implementará después de Chatwoot. |
| Zendesk OAuth app | Sigue pendiente; se implementará después de Chatwoot. |
| Postmark | Falta `POSTMARK_API_TOKEN`, `POSTMARK_FROM_EMAIL` y verificar dominio `auyan.ai`. |
| Weekly Reports cron | Falta setear `DATABASE_URL` en GitHub Actions para el workflow programado. |

---

## Referencias rápidas

- [`docs/progress-archive.md`](progress-archive.md) — historial completo.
- [`docs/auyan-master-context.md`](auyan-master-context.md) — fuente única de verdad negocio + producto.
- [`docs/architecture-agent-v2.md`](architecture-agent-v2.md) — arquitectura técnica del agente.
- [`docs/architecture-web.md`](architecture-web.md) — arquitectura dashboard web.
- [`docs/DESIGN.md`](DESIGN.md) — sistema visual vigente.
- `CLAUDE.md` — reglas operativas del proyecto.
