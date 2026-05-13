# Auyan — Estado del proyecto

_Última actualización: 2026-05-13 (sesión 3 — Sprint 1 cerrado, deploy Railway staging, validación e2e)_

---

## Sprint 0 — Fundación (completado)

- [x] Repositorio creado en GitHub (`Auyan-ai/platform`)
- [x] Estructura de monorepo definida en CLAUDE.md
- [x] CLAUDE.md con reglas completas
- [x] `.gitignore` configurado
- [x] Flujo de ramas definido: `main` → producción, `develop` → staging
- [x] Reglas de selección de modelo documentadas (Sonnet vs Opus)
- [x] Primer PR y flujo de contribución validados ([PR #1](https://github.com/Auyan-ai/platform/pull/1))

---

## Decisiones tomadas

| Decisión | Opción elegida | Alternativas descartadas | Razón |
|---|---|---|---|
| Stack backend | FastAPI (Python) | Django, Node.js | Velocidad de desarrollo, compatibilidad con ecosistema ML/AI |
| Stack frontend | Next.js + TypeScript | React SPA, Vue | App Router, SSR, tipado fuerte |
| Base de datos | Supabase (Postgres + pgvector) | PlanetScale, Firebase | pgvector para embeddings, RLS nativo, Postgres estándar |
| Agente | LangGraph + Claude API | LangChain, Autogen | Control fino del grafo, soporte de estado persistente |
| Observabilidad | Langfuse | Helicone, LangSmith | Open source, trazabilidad por tenant, tracking de costos |
| Inbox operativo | Chatwoot | Zendesk interno, Freshdesk | Open source, API robusta, self-hosteable |
| Multi-tenancy | `tenant_id` en todas las tablas + RLS | Schemas separados por tenant | Operativamente más simple, RLS de Supabase lo hace seguro |
| Soft delete | Columna `deleted_at` | DELETE real | Auditoría, recuperación, historial completo |
| Deploy | Railway | Render, Fly.io, AWS | Simplicidad operativa para la etapa actual |
| Email inbound | Postmark | SendGrid, AWS SES | Webhooks confiables, parsing de email robusto |
| Modelo del agente | `claude-sonnet-4-6` | GPT-4o, Gemini | Mejor relación costo/calidad para respuestas de CX |
| Modelo para diseño/arquitectura | `claude-opus-4-7` | Sonnet | Mayor capacidad de razonamiento para decisiones críticas |

---

## Sprint 1 — Core del sistema (completado)

**Objetivo:** Ticket entra, agente responde, todo queda logueado bajo un tenant de prueba.

**Criterio de done:** ✅ Cumplido — un POST a `/webhooks/inbound` en staging recorre el grafo completo y genera un trace en Langfuse.

### Backend (`apps/api`) — completado en PR #4 + PR #6

- [x] Scaffolding FastAPI completo (`main.py`, `core/`, `db/`, `agents/`, `integrations/`, `routers/`, `tests/`)
- [x] `core/config.py` — pydantic-settings v2, falla en boot si falta var requerida
- [x] `db/client.py` — pool asyncpg con `tenant_scope(tenant_id)` GUC por request
- [x] `db/models.py` + `db/queries.py` — Pydantic v2, queries por área
- [x] Grafo LangGraph — 8 nodos, decorador `@guarded`, threshold override, RAG K=5
- [x] `integrations/langfuse_client.py` — fallback silencioso, trace por conversación
- [x] `integrations/anthropic_client.py` — retry tenacity solo sobre errores transitorios
- [x] `integrations/openai_embeddings.py` — `text-embedding-3-small` (1536 dims)
- [x] `routers/webhooks.py` — `POST /webhooks/inbound` con HMAC-SHA256
- [x] `agents/service.py` — orquestador, mapea state a `AgentOutcome`
- [x] 127 tests, ~1s, todos en verde

### Infraestructura — completado en sesión 3

- [x] Esquema Supabase staging aplicado + tenant `lunaria` provisionado (seed completo)
- [x] 22 variables de entorno subidas a Railway staging (Supabase, Anthropic, OpenAI, Langfuse, webhook secret, defaults del agente)
- [x] `railway.toml` en raíz + `Dockerfile` reescrito para Railway:
  - Build context = repo root (necesario para imports `apps.api.*`)
  - Poetry 1.8 instala dependencias de producción
  - CMD usa `${PORT:-8000}` — Railway asigna el puerto dinámicamente
- [x] Deploy en Railway staging: `https://platform-staging-fdb7.up.railway.app`
  - `GET /health` → `{"ok": true, "env": "staging"}`
- [x] Validación e2e con POST real a `/webhooks/inbound`:
  - Firma HMAC validada ✅
  - Tenant resuelto, customer upsert, conversación y mensaje persistidos en Supabase ✅
  - Grafo invocado, trace en Langfuse generado (`trace_id: 388d3440-f518-47ce-a742-921a4b5ce234`) ✅
  - Manejo de error y escalación registrados ✅
  - **Respuesta del agente bloqueada por cuota OpenAI** (ver pendiente abajo)

### Único pendiente para respuesta real del agente

- [ ] **Agregar créditos a la cuenta OpenAI** — el nodo `retrieve_knowledge` falla con `429 insufficient_quota` al intentar generar embeddings con `text-embedding-3-small`. Una vez con créditos, el agente responderá en lugar de escalar por error.
- [ ] **Sincronizar `WEBHOOK_SECRET` en el `.env` local** — el secreto local difiere del que Railway tiene. Copiar el valor de `railway variables --json | jq -r .WEBHOOK_SECRET` al `.env` local.

### Bugs encontrados y resueltos en sesión 3

| Bug | Causa raíz | Fix |
|---|---|---|
| `PORT` hardcodeado en Dockerfile | Railway asigna puerto dinámicamente vía `$PORT` | `CMD ["sh", "-c", "uvicorn ... --port ${PORT:-8000}"]` ([PR #9](https://github.com/Auyan-ai/platform/pull/9)) |
| `agent_service` tratado como query param | `AgentService` bajo `TYPE_CHECKING` → `get_type_hints()` falla en runtime → FastAPI degrada el `Depends` | Mover import fuera de `TYPE_CHECKING` ([PR #10](https://github.com/Auyan-ai/platform/pull/10)) |
| Vars Railway con comentarios inline | Script de upload tomaba todo el valor después del `=`, incluyendo `# comentario` | Bash `source` sí los stripea; el script Python no. Corregido manualmente para `WEBHOOK_SECRET`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` |

---

## Deuda técnica registrada para Sprint 2

- **Script de upload de vars a Railway debe stripear comentarios inline** — el script actual toma todo lo que hay después del `=`, incluyendo `# comentarios`. Reescribirlo para parsear `.env` igual que bash.
- **Refactor de services + routers al paradigma asyncpg** — se eliminaron `services/{tickets,tenants,escalation}.py`, `routers/{tickets,tenants}.py`, `core/security.py` durante el merge con el PR del grafo porque dependían de `supabase-py` (sync). Hay que reescribirlos con `asyncpg + tenant_scope`.
- **Rol `auyan_backend` en Supabase con `NOBYPASSRLS`** — actualmente conectamos con `postgres` (bypass RLS). La defensa multi-tenant depende solo de `WHERE tenant_id = $1` y el GUC por request.
- **Tests de integración contra Postgres+pgvector real** — hoy todo es unit con mocks.
- **Integraciones de canales** (`chatwoot.py`, `zendesk.py`, `shopify.py`) son clientes HTTP esqueleto — cablear con el flujo del agente.
- **`poetry.lock` ausente** — las builds de Railway resuelven dependencias en cada deploy. Generar el lock file para builds reproducibles.

---

## Backlog (Sprint 2+)

- Integración Chatwoot bidireccional
- Integración Zendesk (webhook receiver + API)
- Integración Shopify (pedidos, cancelaciones, devoluciones)
- Dashboard interno (`apps/web/app/dashboard/`)
- Dashboard cliente por tenant (`apps/web/app/clients/`)
- Chat widget embebible (`apps/widget`)
- WhatsApp vía Twilio o 360dialog
- Instagram vía Meta API
- Email inbound vía Postmark
- Onboarding flow para nuevos tenants
