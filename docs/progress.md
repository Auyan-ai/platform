# Auyan — Estado actual

_Última actualización: 2026-05-28 (sesión 46 — Bloque 1.7 completado y archivado; siguiente paso técnico: Bloque 1.8 landing pública)._

> Historial completo en [`docs/progress-archive.md`](progress-archive.md). Contexto estratégico en [`docs/auyan-master-context.md`](auyan-master-context.md).

---

## Empezar aquí

**Modelo recomendado:** Sonnet para continuar Bloque 1.

**Rama actual esperada:** `develop`.

**Estado general:**

| Área | Estado |
|---|---|
| Bloque 0 | 0.1–0.10 completados. 0.11 sigue bloqueado por crédito Anthropic para corrida final con judge. |
| Bloque 1 | 1.0–1.7 completados y archivados. |
| Siguiente paso | 1.8 — Landing pública (`apps/landing` + Aceternity UI + Plausible). |

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

### Siguiente: Sub-PR 1.8 — Landing pública

**Objetivo:** crear la landing pública de Auyan según el contexto maestro: Managed AI Service para CX e-commerce, primer viewport claro, captación founding partners y medición con Plausible.

Scope recomendado:

1. `apps/landing` como app pública separada.
2. Copy alineado a `auyan-master-context.md`: resultado operacional, no SaaS self-serve.
3. CTA hacia demo / contacto founding partner.
4. Plausible listo para configurar por env.

### Nota para 1.4 — Shopify content import / KB bootstrap

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

## Migraciones listas para staging

Estas migraciones ya están en repo y listas para aplicar en staging:

| Migración | Incluye |
|---|---|
| `20260525000001_add_tenant_playbook.sql` | `tenant_playbook` |
| `20260525000002_add_tenant_facts.sql` | `tenant_facts` |
| `20260527000001_add_tenant_onboarding.sql` | `agent_lifecycle_state` + `tenant_onboarding` |
| `20260528000001_add_tenant_knowledge_submissions.sql` | `tenant_knowledge_submissions` + cola KB |
| `20260528000002_add_weekly_reports.sql` | `weekly_reports` + flujo `draft/pending_review/approved/sent/failed` |

Pendiente operativo: aplicarlas manualmente en Supabase/Railway staging antes de depender de estas tablas en ambiente real. El cron de reportes semanales requiere además `DATABASE_URL` como secret de GitHub Actions.

---

## Pendientes vivos

### Bloque 0.11 — Validación E2E

Bloqueado por crédito Anthropic.

Cuando haya crédito:

1. Re-seed AOPs: `seed_test_aops.py --tenant <Lunaria> --update`.
2. Mapa barato sin judge: `run_simulator.py --tenant <Lunaria> --reseed --no-judge --all`.
3. Arreglar lo que quede.
4. Corrida final con judge para confirmar meta ≥20/25.

Tenant de prueba Lunaria staging: `11111111-1111-1111-1111-111111111111`.

### Staging / servicios externos

| Pendiente | Estado |
|---|---|
| Gorgias OAuth app | Falta registrar app + setear env vars. |
| Zendesk OAuth app | Falta registrar app + setear env vars. |
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
