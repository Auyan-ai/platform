# Auyan — Estado del proyecto

_Última actualización: 2026-05-13 (sesión 2)_

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

### Estado del repo
El repositorio contiene únicamente documentación. Ninguna carpeta de código (`apps/`, `packages/`) existe todavía — todo está por construir.

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

## Sprint 1 — Core del sistema (en curso)

**Objetivo:** Tener el sistema funcionando end-to-end con un solo tenant de prueba: ticket entra, agente responde, todo queda logueado.

### Backend (`apps/api`)
- [x] Scaffolding inicial de FastAPI (`apps/api/main.py`, estructura completa de carpetas)
  - `core/`, `db/`, `agents/`, `agents/nodes/`, `agents/prompts/`, `integrations/`, `routers/`, `tests/`
  - `pyproject.toml` con poetry, runtime stack (fastapi, langgraph, anthropic, openai, asyncpg+pgvector, langfuse, tenacity, structlog) y dev (pytest, ruff, mypy estricto)
- [x] Configuración de variables de entorno (`core/config.py`)
  - `Settings` con pydantic-settings v2; falla en boot si falta cualquier var requerida
  - Singleton vía `lru_cache`; validators para `rag_min_similarity ∈ [0,1]` y `embedding_dimensions == 1536`
- [x] Esquema de Supabase con multi-tenant y RLS (`supabase/migrations/20260513000000_initial_schema.sql`)
  - Tablas: `tenants`, `users` (staff), `end_customers`, `conversations`, `messages`, `escalations`, `knowledge_base_documents`, `knowledge_base_chunks` (pgvector 1536), `tenant_configurations`, `tenant_prompts` (versionados)
  - RLS por JWT claim `tenant_id` + rol `super_admin` para Auyan
  - FKs compuestas `(id, tenant_id)` para impedir cross-tenant
  - Soft delete (`deleted_at`) y `updated_at` automático en todas
- [x] Modelos y queries base
  - `db/client.py`: pool global de asyncpg con codec JSONB↔dict y `register_vector` por conexión; `tenant_scope(tenant_id)` setea `app.tenant_id` GUC local; `bootstrap_connection()` para resolver tenant
  - `db/models.py`: Pydantic v2 con enums espejados como `Literal[...]`
  - `db/queries.py`: queries organizadas por área (tenants, customers, conversations, messages, escalations, KB) con cast explícito a enums Postgres
- [x] Grafo inicial de LangGraph (`agents/graph.py` + `agents/nodes/*`)
  - 8 nodos: `load_tenant_context`, `load_conversation`, `retrieve_knowledge`, `reason`, `respond`, `escalate`, `handle_error`, `finalize_trace`
  - Decorador `@guarded` envuelve nodos de preparación: short-circuit en error previo + captura de excepciones
  - Una sola conditional edge (post `reason`) con 3 destinos: respond / escalate / handle_error
  - `reason` aplica threshold override: si `decision='respond'` y `confidence < tenant.escalation_threshold`, fuerza escalate con razón `low_confidence: X < Y`
  - Schema del tool output validado con Pydantic (`AgentDecisionTool`) — `extra='forbid'`, coherencia respond/escalate
  - RAG: K=5, similitud mínima 0.6, vía pgvector con HNSW
  - Historial: últimos 20 mensajes raw, mapeo customer→user / agent_*→assistant, coalesce de roles consecutivos
- [x] Integración con Langfuse (`integrations/langfuse_client.py`)
  - Wrapper con fallback silencioso: si Langfuse cae, el agente sigue funcionando
  - Trace por conversación con tags por tenant + canal; nivel ERROR si hubo `error` en el grafo
  - Flush en thread separado para no bloquear el event loop
- [x] Webhook receiver básico (`routers/webhooks.py`)
  - `POST /webhooks/inbound` con HMAC-SHA256 (`X-Auyan-Signature: sha256=<hex>`)
  - Flujo: validar firma → parsear payload → resolver tenant → upsert customer → find-or-create conversation → INSERT inbound → `agent_service.process_inbound` → respuesta JSON con outcome
  - Códigos: 200 happy, 400 payload inválido, 401 firma inválida, 403 tenant inactivo, 404 tenant no encontrado
- [x] Orquestador `AgentService` (`agents/service.py`)
  - Abre/cierra trace de Langfuse alrededor de `graph.ainvoke`
  - Mapea final state a `AgentOutcome` (dataclass frozen)
  - Recovery ante excepciones no-guardadas del propio LangGraph
- [x] Cliente Anthropic con retry (`integrations/anthropic_client.py`)
  - `call_claude_with_tool` con `tool_choice` forzado
  - Tenacity: 3 reintentos exponenciales sólo sobre errores transitorios (APIConnectionError, APITimeoutError, RateLimitError, InternalServerError); 4xx no reintenta
- [x] Cliente OpenAI para embeddings (`integrations/openai_embeddings.py`)
  - `get_query_embedding` con `text-embedding-3-small` (1536 dims) y retries
- [x] Pricing por modelo (`integrations/pricing.py`)
  - Tarifas verificadas 2026-05-13: Sonnet 4.6 ($3/$15), Opus 4.7 ($5/$25), Haiku 4.5 ($1/$5)
  - Nota documentada sobre tokenizer actualizado de Opus 4.7: mismo texto puede mapearse a 1.0–1.35× tokens vs versiones previas ([fuente](https://www.anthropic.com/news/claude-opus-4-7))
- [x] Tests por módulo (`apps/api/tests/`, 127 tests en ~1s)
  - **Lógica pura:** schemas Pydantic, prompts builder (coalesce, mapeo, defensa último-user), pricing, HMAC signature, routing function
  - **Nodos individuales** con `tenant_scope` y queries mockeadas: cada nodo del grafo con happy + error paths
  - **Guard decorator:** passthrough con error previo, captura de excepciones con nombre del nodo
  - **AgentService:** mapping a outcome, recovery ante graph exception, langfuse opcional
  - **LangfuseClient:** swallow de excepciones del SDK, flush en thread
  - **Anthropic retry:** reintenta transitorios, NO reintenta 4xx, propaga al exhaustar
  - **OpenAI embeddings:** retries, rechaza texto vacío
  - **Grafo end-to-end:** construye `build_graph(deps)` real e invoca con todas las dependencias externas mockeadas — valida que las edges conectan los 3 caminos: respond / escalate / handle_error
  - **Webhook endpoint HTTP** con FastAPI TestClient: 200, 400, 401, 403, 404 — firma validada ANTES del parsing del payload

### Infraestructura
- [x] `.env.example` con todas las variables necesarias (raíz del repo, según CLAUDE.md)
- [ ] `docker-compose.yml` para levantar servicios localmente (Postgres+pgvector, Langfuse local, API)
- [ ] Deploy inicial en Railway (entorno staging)

### Deuda técnica registrada para Sprint 2
- Crear rol `auyan_backend` en Supabase con `NOBYPASSRLS` y grants equivalentes a `authenticated`. Actualmente conectamos con `postgres` (bypass RLS) y la defensa multi-tenant queda en (a) `WHERE tenant_id = $1` explícito en todas las queries y (b) GUC `app.tenant_id` seteado por request. Pragmático para v1 pero quita una capa de defensa.
- Tests de integración contra Postgres+pgvector real (queries SQL, RLS, HNSW). Hoy todo es unit con mocks.
- Validadores de `Settings` no testeados (requieren env vars reales).

### Criterio de done del Sprint 1
Un ticket enviado vía POST al endpoint de la API es procesado por el agente, genera una respuesta, y el trace completo aparece en Langfuse — todo bajo un `tenant_id` de prueba.

**Estado actual del done:** falta sólo el `docker-compose.yml` + provisioning del tenant de prueba en una DB real + deploy. La lógica está toda armada y testeada con mocks.

---

## Sesión 2026-05-13 (sesión 2) — Grafo de LangGraph end-to-end

**Diseño aprobado antes de implementar.** El diseño completo (AgentState, nodos, transiciones, flujo end-to-end de un mensaje, manejo de errores, observabilidad) se acordó con el usuario en chat antes de tirar la primera línea de código.

**Decisiones técnicas registradas:**
1. Embeddings: OpenAI `text-embedding-3-small` (simplicidad; migración a Voyage si la calidad no alcanza).
2. Historial: últimos 20 mensajes raw (resumen acumulado en v2).
3. RAG: K=5, similitud mínima 0.6.
4. Reintentos: 3 con backoff exponencial.
5. El caller envía la respuesta al canal; el grafo sólo decide y persiste.
6. Pydantic valida el tool output de Claude.

**Implementación en grupos con revisión entre cada uno:**
- Grupo 1: pyproject + config + .env.example
- Grupo 2: db/ completo
- Grupo 3: agents/ + grafo + nodos + integraciones LLM
- Grupo 4: routers + Langfuse + AgentService + main.py
- Grupo 5: 127 tests, 0 fallos
- Grupo 6: este progress + PR

**Próximo paso:** revisar el PR, mergearlo a `develop`, y arrancar Sprint 1 final: `docker-compose.yml` con Postgres+pgvector+Langfuse local, provisionar tenant de prueba, validar el flujo end-to-end con una conversación real.

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
