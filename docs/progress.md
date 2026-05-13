# Auyan — Estado del proyecto

_Última actualización: 2026-05-13 (sesión 3 — reconciliación tras merge de PR #4 y PR #6)_

---

## Sprint 0 — Fundación (completado)

**Objetivo:** Establecer las bases del proyecto antes de escribir una línea de código productivo.

### Completado
- [x] Repositorio creado en GitHub (`Auyan-ai/platform`)
- [x] Estructura de monorepo definida en CLAUDE.md (`apps/api`, `apps/web`, `apps/widget`, `packages/shared`, `docs`)
- [x] CLAUDE.md con reglas completas: multi-tenant, RLS, soft delete, observabilidad, flujo del agente, integraciones previstas, organización de archivos
- [x] `.gitignore` configurado (incluye `.DS_Store`, `.env`)
- [x] Flujo de ramas definido: `main` → producción, `develop` → staging, `feature/*` y `fix/*` para trabajo
- [x] Reglas de selección de modelo documentadas (Sonnet vs Opus según tarea)
- [x] Primer PR abierto y flujo de contribución validado ([PR #1](https://github.com/Auyan-ai/platform/pull/1))

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

## Sprint 1 — Core del sistema (completado en código — pendiente provisioning)

**Objetivo:** Tener el sistema funcionando end-to-end con un solo tenant de prueba: ticket entra, agente responde, todo queda logueado.

### Backend (`apps/api`) — completado
- [x] Scaffolding inicial de FastAPI (`apps/api/main.py`, estructura completa de carpetas)
  - `core/`, `db/`, `agents/`, `agents/nodes/`, `agents/prompts/`, `integrations/`, `routers/`, `tests/`
  - `pyproject.toml` con poetry, runtime stack (fastapi, langgraph, anthropic, openai, asyncpg+pgvector, langfuse, tenacity, structlog) y dev (pytest, ruff, mypy estricto)
  - `Dockerfile` multi-stage para Railway
- [x] Configuración de variables de entorno (`core/config.py`)
  - `Settings` con pydantic-settings v2; falla en boot si falta cualquier var requerida
  - Singleton vía `lru_cache`; validators para `rag_min_similarity ∈ [0,1]` y `embedding_dimensions == 1536`
- [x] `.env.example` con todas las variables necesarias (raíz del repo)
- [x] `docker-compose.yml` para levantar la API localmente
  - Servicios: `api` (FastAPI) + `redis:7-alpine`
  - **Nota:** no incluye Postgres ni Langfuse local — asume Supabase cloud y Langfuse cloud vía `.env`
- [x] Esquema de Supabase con multi-tenant y RLS (`supabase/migrations/`)
  - Tablas: `tenants`, `users`, `end_customers`, `conversations`, `messages`, `escalations`, `knowledge_base_documents`, `knowledge_base_chunks` (pgvector 1536), `tenant_configurations`, `tenant_prompts`
  - RLS por JWT claim `tenant_id` + rol `super_admin` para Auyan
  - FKs compuestas `(id, tenant_id)` para impedir cross-tenant
  - Soft delete (`deleted_at`) y `updated_at` automático en todas
- [x] Modelos y queries base
  - `db/client.py`: pool global asyncpg con codec JSONB↔dict y `register_vector`; `tenant_scope(tenant_id)` setea GUC local
  - `db/models.py`: Pydantic v2 con enums espejados como `Literal[...]`
  - `db/queries.py`: queries por área (tenants, customers, conversations, messages, escalations, KB) con cast explícito a enums Postgres
- [x] Grafo de LangGraph (`agents/graph.py` + `agents/nodes/*`)
  - 8 nodos: `load_tenant_context`, `load_conversation`, `retrieve_knowledge`, `reason`, `respond`, `escalate`, `handle_error`, `finalize_trace`
  - Decorador `@guarded`: short-circuit en error previo + captura de excepciones
  - Una sola conditional edge (post `reason`) con 3 destinos: respond / escalate / handle_error
  - Threshold override: si `decision='respond'` y `confidence < escalation_threshold`, fuerza escalate
  - Schema del tool output validado con Pydantic (`AgentDecisionTool`) — `extra='forbid'`
  - RAG: K=5, similitud mínima 0.6, vía pgvector HNSW
  - Historial: últimos 20 mensajes, coalesce de roles consecutivos
- [x] Integración Langfuse (`integrations/langfuse_client.py`)
  - Wrapper con fallback silencioso: si Langfuse cae, el agente sigue
  - Trace por conversación con tags por tenant + canal; flush en thread separado
- [x] Webhook receiver (`routers/webhooks.py`)
  - `POST /webhooks/inbound` con HMAC-SHA256 (`X-Auyan-Signature: sha256=<hex>`)
  - Flujo: validar firma → parsear payload → resolver tenant → upsert customer → find-or-create conversation → INSERT inbound → `agent_service.process_inbound`
  - Códigos: 200 happy, 400 payload inválido, 401 firma inválida, 403 tenant inactivo, 404 tenant no encontrado
- [x] Orquestador `AgentService` (`agents/service.py`)
  - Abre/cierra trace Langfuse alrededor de `graph.ainvoke`; mapea final state a `AgentOutcome`
- [x] Cliente Anthropic con retry (`integrations/anthropic_client.py`)
  - Tenacity: 3 reintentos exponenciales solo sobre errores transitorios; 4xx no reintenta
- [x] Cliente OpenAI para embeddings (`integrations/openai_embeddings.py`)
  - `text-embedding-3-small` (1536 dims) con retries
- [x] Pricing por modelo (`integrations/pricing.py`)
- [x] Tests por módulo (`apps/api/tests/`, 127 tests — ~1s)
  - Schemas, prompts builder, pricing, HMAC, routing, nodos individuales, guard decorator, AgentService, LangfuseClient, Anthropic retry, OpenAI embeddings, grafo e2e, webhook HTTP

### Infraestructura — pendiente
- [x] `.env.example` y `docker-compose.yml` presentes en el repo
- [ ] **Provisionar tenant de prueba en Supabase staging real** — correr las migrations en el proyecto Supabase de staging e insertar un tenant seed
- [ ] **Deploy inicial en Railway (staging)** — conectar repo, configurar env vars, primer deploy exitoso
- [ ] **Validación end-to-end real** — enviar un POST a `/webhooks/inbound` contra el deploy de staging, confirmar respuesta del agente y trace en Langfuse

### Criterio de done del Sprint 1
Un ticket enviado vía POST al endpoint de la API es procesado por el agente, genera una respuesta, y el trace completo aparece en Langfuse — todo bajo un `tenant_id` de prueba.

**Estado actual:** toda la lógica está implementada y testeada con mocks. Faltan los 3 pasos de infraestructura de arriba para declarar el sprint completamente cerrado.

---

## Deuda técnica registrada para Sprint 2

- **Refactor de services + routers al paradigma asyncpg.** Se eliminaron `services/{tickets,tenants,escalation}.py`, `routers/{tickets,tenants}.py`, `core/security.py` y `tests/test_health.py` porque dependían de `supabase-py` (sync), incompatible con `asyncpg + tenant_scope`. Hay que reescribirlos: endpoint `POST /tickets/inbound` (interno, sin HMAC), `GET /tenants/{id}`, auth JWT vía Supabase, test de `/health`.
- **Rol `auyan_backend` en Supabase con `NOBYPASSRLS`.** Actualmente conectamos con `postgres` (bypass RLS) — la defensa multi-tenant queda en `WHERE tenant_id = $1` explícito y GUC `app.tenant_id`. Pragmático para v1 pero falta una capa de defensa.
- **Tests de integración contra Postgres+pgvector real** (queries SQL, RLS, HNSW). Hoy todo es unit con mocks.
- **Integraciones de canales esqueleto** (`chatwoot.py`, `zendesk.py`, `shopify.py`) — cablear con el flujo del agente.

---

## Backlog (post Sprint 1)

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
