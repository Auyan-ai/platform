# Auyan — Archivo histórico de sprints (pre-pivot)

> Este archivo contiene el historial completo de Sprints 0-11, Rate Limiting, y el pivot de 2026-05-22.
> El estado activo del proyecto vive en [`progress.md`](progress.md).

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
- [x] 22 variables de entorno subidas a Railway staging
- [x] `railway.toml` en raíz + `Dockerfile` reescrito para Railway
- [x] Deploy en Railway staging: `https://platform-staging-fdb7.up.railway.app`
- [x] Validación e2e con POST real a `/webhooks/inbound` — trace en Langfuse generado

### Bugs encontrados y resueltos en sesión 3

| Bug | Causa raíz | Fix |
|---|---|---|
| `PORT` hardcodeado en Dockerfile | Railway asigna puerto dinámicamente vía `$PORT` | `CMD ["sh", "-c", "uvicorn ... --port ${PORT:-8000}"]` ([PR #9](https://github.com/Auyan-ai/platform/pull/9)) |
| `agent_service` tratado como query param | `AgentService` bajo `TYPE_CHECKING` → `get_type_hints()` falla en runtime | Mover import fuera de `TYPE_CHECKING` ([PR #10](https://github.com/Auyan-ai/platform/pull/10)) |

---

## Sprint 2 — Refactor services/routers a asyncpg (completado)

**Objetivo:** Endpoints administrativos (tenants, conversations, escalations) sobre asyncpg + auth Supabase JWT real.

### Patrón acordado

```
routers/   → HTTP + validación + scope de transacción
services/  → reglas de negocio multi-paso, reciben conn: asyncpg.Connection
db/queries → SQL puro, función + conn + params, devuelve modelos Pydantic
core/      → security (JWT), errors (DomainError)
```

### Avances sesión 4 (5 commits)

- `core/errors.py` — `DomainError` + subclases (`NotFoundError`, `ForbiddenError`, `UnauthorizedError`, `ConflictError`, `ValidationFailed`)
- `core/security.py` — `AuthContext`, `get_auth_context`, `get_tenant_id`, `require_role`, cache TTL
- `pyjwt` (preferido sobre python-jose por CVEs) + `cachetools` con `TTLCache(maxsize=1000, ttl=60s)`
- Suite total 157 verde

### Avances sesión 5

- 6 queries nuevas: `list_conversations`, `get_messages_for_conversation`, `get_escalation`, `list_escalations`, `claim_escalation` (CAS), `resolve_escalation` (CAS)
- Services: `tenants`, `conversations`, `escalations`
- Routers: `GET /tenants/me`, `/conversations`, `/escalations` con acciones
- Suite total 182 verde

### Sesión 6 — smoke test + fix ES256

| PR | Qué hace |
|---|---|
| [PR #12](https://github.com/Auyan-ai/platform/pull/12) | `.claude/` agregado a `.gitignore` |
| [PR #13](https://github.com/Auyan-ai/platform/pull/13) | `supabase/seed.sql`: fix columnas GoTrue + insert en `auth.identities` |
| [PR #14](https://github.com/Auyan-ai/platform/pull/14) | `feat/sprint2-services-asyncpg` → `develop`. Sprint 2 completo mergeado. |
| [PR #15](https://github.com/Auyan-ai/platform/pull/15) | `fix(auth): ES256 JWKS support`. Supabase usa ES256 en proyectos nuevos. `security.py` reescrito para verificar JWT con clave pública del JWKS. |
| [PR #16](https://github.com/Auyan-ai/platform/pull/16) | `cryptography>=44.0` + `pyjwt[crypto]` en `poetry.lock`. |

**Validado e2e:** `GET /tenants/me` con JWT real → 200. `GET /tenants/me` sin token → 401.

**Issue Railway auto-deploy:** el GitHub App de Railway dejó de disparar builds tras PR #14. Workaround: mutation `environmentTriggersDeploy` por GraphQL con HTTP/1.1.

---

## Sprint 3 — Dashboard interno (completado ✅)

**Objetivo:** Dashboard `apps/web` que consuma los endpoints admin del API como super_admin.

**URLs de staging:**
- API: `https://platform-staging-fdb7.up.railway.app`
- Web: `https://auyan-web-staging.up.railway.app`

### Sub-PR 3.1 — Scaffolding + Auth + Login

- pnpm 11.1.2 + workspaces, `biome.json`, `packages/shared`
- Next.js 15 App Router, TypeScript strict, Tailwind v4, shadcn, Biome
- `@supabase/ssr`: `lib/supabase/client.ts` + `lib/supabase/server.ts`, middleware, `/login`

### Sub-PR 3.2 — API client tipado

- `api-types.ts` generado desde staging `/openapi.json`
- `lib/api/client.ts` con `openapi-fetch` + TanStack Query

### Sub-PR 3.3 — Inbox conversaciones ([PR #19](https://github.com/Auyan-ai/platform/pull/19))

- `ConversationList.tsx` con filtros de status (6 tabs), polling 5s, paginación
- `CORSMiddleware` agregado al API

### Sub-PR 3.4 — Detalle conversación ([PR #20](https://github.com/Auyan-ai/platform/pull/20))

- `ConversationDetail.tsx` — hilo con burbujas, composer (Responder / Escalar / Cerrar)

### Sub-PR 3.5 — Cola escalaciones ([PR #21](https://github.com/Auyan-ai/platform/pull/21))

- `EscalationQueue.tsx` con filtros, botones Tomar/Resolver

### Sub-PR 3.6 — Tenant switcher ([PR #22](https://github.com/Auyan-ai/platform/pull/22))

- `GET /tenants/admin/list` + `TenantSwitcher.tsx` + `Sidebar.tsx` dinámico

### Sub-PR 3.7 — Deploy web ([PR #24](https://github.com/Auyan-ai/platform/pull/24) + fixes #26–#29)

- `apps/web/Dockerfile` multistage pnpm, Next.js standalone
- Servicio `auyan-web` creado en Railway

---

## Sprint 4 — Dashboard cliente por tenant ([PR #31](https://github.com/Auyan-ai/platform/pull/31)) ✅

**Objetivo:** Vista read-only para `tenant_admin`.

- `GET /users/me` + `GET /tenants/me/metrics` (API)
- Post-login routing por rol: `tenant_admin` → `/clients/{id}/overview`, otros → `/dashboard`
- `MetricsCards.tsx`, `RecentConversations.tsx`, vistas read-only (ConversationList, ConversationDetail, EscalationQueue con props `readOnly`)
- Flujo `tenant_admin` validado en staging con fixes PR #37–#39

---

## Sprint 5 — Mejoras al grafo (completado ✅)

Bugs encontrados en e2e → [PR #40](https://github.com/Auyan-ai/platform/pull/40):

- `escalate.py` persiste mensaje del agente en el hilo
- Sin escalaciones duplicadas — `get_open_escalation_for_conversation` detecta activas

**Suite total: 193/193 verde.**

---

## Deuda técnica registrada (histórico)

- Script de upload de vars a Railway debe stripear comentarios inline
- Rol `auyan_backend` en Supabase con `NOBYPASSRLS` — actualmente usamos `postgres` (bypass RLS)
- Tests de integración contra Postgres+pgvector real — hoy todo es unit con mocks
- Errores mypy preexistentes en `db/models.py`, `db/queries.py`, `db/client.py`, `core/config.py` (14 errors `[type-arg]` y `[no-any-return]`)
- `search_products` usa `?title=` (coincidencia exacta) — migrar a Admin GraphQL API para búsqueda full-text real
- Conflicto Shopify snowboards vs KB joyería (tienda de prueba auto-generada como snowboards)
- Context engineering gaps (sesión 19): memory cross-conversación, glossary block, brand voice por AOP, detección alucinaciones automática

Resueltos en sesiones posteriores:
- ~~Webhook idempotency~~ → Sprint 9.1
- ~~Rate limiting + cost controls~~ → Rate Limiting
- ~~Razonamiento del agente visible~~ → Sprint 8
- ~~CI ausente~~ → PR #41
- ~~`.claude/` no en `.gitignore`~~ → PR #12
- ~~`poetry.lock` ausente~~ → sesión 4

---

## Sesión 10 — Diseño arquitectural agente v2 (2026-05-17)

**Sin commits** — sesión de diseño puro. Resultado: [`docs/architecture-agent-v2.md`](architecture-agent-v2.md).

### Lo que se decidió

1. **Skills framework** — cada acción es clase tipada con I/O Pydantic, registrada en registry, con tier L1/L2/L3.
2. **AOPs (Agent Operating Procedures)** — YAML frontmatter + markdown body, editable runtime desde dashboard.
3. **Supervisor pattern** — Sonnet supervisa L1/L2, Opus supervisa L3.
4. **Slow agent** — LLM-as-judge post-mortem con sampling + Sonnet first.

### Decisiones lockeadas

- **AOP storage:** DB con versionado append-only + workspaces (prod/staging)
- **Supervisor:** Sonnet para L1/L2, Opus para L3, con `reject_kind: tactical | structural`
- **Eval harness:** obligatorio Sprint 7, gate 80% para promotion
- **PII policy:** pseudonimización con salt por tenant, retención 90d hot / 180d hash

### Plan multi-sprint (lockeado)

| Sprint | Foco |
|---|---|
| 6 | Skills framework + Shopify L1 + ReAct loop |
| 7 | AOPs en DB + selector + workspaces + UI + eval harness |
| 8 | Supervisor pattern |
| 9 | Skills L2 + permissions + audit PII + idempotency |
| 10 | Skills L3 + human approval mode |
| 11 | Slow agent |
| 12 | Unified KB + Zendesk bidireccional |
| 14+ | MCP server |

---

## Sprint 6 — Skills framework + Shopify L1 + ReAct loop

### Sub-PR 6.1 — Skills framework

- `skills/base.py` — `SkillTier`, `Skill` ABC, `to_anthropic_tool()`, `TIER_THRESHOLDS`
- `skills/registry.py` — `SkillRegistry` singleton con decorator
- 39 tests (25 base + 14 registry)

### Sub-PR 6.2 — Shopify L1 + cliente ([PR #44](https://github.com/Auyan-ai/platform/pull/44))

- `integrations/shopify.py` reescrito con 8 métodos
- 5 skills L1: `shopify.get_order_by_email`, `get_order_status`, `get_product_info`, `get_customer_history`, `get_shop_policies`
- Suite total: 270/270

### Sub-PR 6.3a — execute_skill node + state ([PR #46](https://github.com/Auyan-ai/platform/pull/46))

- Campos ReAct en `agents/state.py`
- `agents/nodes/execute_skill.py` — resuelve slug, valida input, ejecuta

### Sub-PR 6.3b — loop ReAct cableado ([PR #47](https://github.com/Auyan-ai/platform/pull/47))

- `call_claude_with_tools` (plural), `reason.py` reescrito, grafo cableado
- Suite total: 311/311

### Sub-PR 6.3c — bootstrap SkillRegistry ([PR #49](https://github.com/Auyan-ai/platform/pull/49))

- Side-effect imports en `skills/__init__.py` + `skills/shopify/__init__.py` + `main.py`
- Suite total: 317/317

### Validación e2e staging (sesión 12)

| Prueba | Skill | Resultado |
|---|---|---|
| "¿Política de devoluciones?" | `shopify.get_shop_policies` | Datos reales ✅ |
| "¿Dónde está mi pedido?" | — | Agente pidió email ✅ |
| "Pedidos por email" | `shopify.get_order_by_email` | Consultó Shopify ✅ |
| "¿Tienen vestidos de noche?" | `shopify.get_product_info` | Detectó joyería ✅ |

### Sub-PR 6.4 — Lifecycle de conversación ([PR #51](https://github.com/Auyan-ai/platform/pull/51))

- `closed_abandoned` enum + `get_stale_conversations` + `mark_conversations_abandoned`
- `services/cleanup.py` — orquestador con timeouts por canal
- `_cleanup_loop` asyncio task en lifespan — cada 15 min
- Suite total: 331/331

---

## Sprint 7 — AOPs en DB + selector de intent + UI editor (completado ✅)

### Sub-PR 7.1 — Tablas DB + modelos + queries

- Migración: `aops`, `aop_versions` (trigger immutabilidad), `intent_classifier_runs`
- 19 tests unitarios

### Sub-PR 7.2 — AOP compiler + TTL cache

- `compile_aop` (6 bloques), `load_aop` con `TTLCache(maxsize=1000, ttl=60)`
- 38 tests

### Sub-PR 7.3/7.4 — Nodo select_aop + grafo

- Clasificador de intent con Haiku (tool-forced), fallback `default`
- Degradación elegante: tenants sin AOPs siguen usando `tenant_prompts` legacy
- 23 tests

### Sub-PR 7.5 — UI editor AOPs

- CRUD completo + `POST /aops/validate`
- `AopList`, `AopEditor`, `AopEditView` + páginas dashboard

### Sub-PR 7.6 — Eval harness + promote endpoint

- 10 tipos de aserciones en `evals/harness.py`
- `PATCH /aops/{id}/promote` — gate 80%, copia a production workspace
- Suite total: 450/450

### Bugs post-Sprint 7 (sesión 16)

| Bug | Fix |
|---|---|
| FK composite `(assigned_user_id, tenant_id)` bloquea super_admin | [PR #56](https://github.com/Auyan-ai/platform/pull/56): FK simple a `users(id)` en `escalations`/`conversations` |
| FK composite en `messages.author_user_id` | [PR #57](https://github.com/Auyan-ai/platform/pull/57): FK simple |
| `aops` table no existe en staging | Migración aplicada manualmente vía psql |

**Lección:** Nunca usar FK composite `(user_id, tenant_id)` en tablas operacionales — bloquea a super_admin.

---

## Sprint 8 — Agent Reasoning UI (completado ✅)

**Objetivo:** Que operadores vean en tiempo real qué está haciendo el agente — sin ir a Langfuse.

### Sub-PR 8.1 — Migración + ReasoningTracker + nodos ([PR #59](https://github.com/Auyan-ai/platform/pull/59))

- Tabla `agent_reasoning_events` con RLS
- `ReasoningTracker` fire-and-forget vía `asyncio.create_task`
- Nodos `load_tenant_context`, `reason`, `execute_skill`, `respond`, `escalate` emiten eventos

### Sub-PR 8.2 — Endpoints REST + SSE

- `GET /conversations/{id}/reasoning` (REST historial)
- `GET /conversations/{id}/reasoning/stream` (SSE, poll cada 1s, max 5min, `Last-Event-ID`)

### Sub-PR 8.3 — Componentes React

- `ToolCallChip`, `ReasoningItem`, `ReasoningPhase`, `AgentReasoningPanel`
- PII masking por regex en vista tenant

### Sub-PR 8.4 — Integración dashboards

- `ConversationDetail.tsx` con prop `maskPII?`

### Sub-PR 8.5 — Supervisor pattern

- `agents/nodes/supervise.py`: `needs_supervision`, modelo Opus para L3 / Sonnet resto
- Primer rechazo táctico → retry; rechazo estructural → escalate
- Suite total: 478/478

### Bugs post-Sprint 8 (sesión 18)

| Bug | Fix |
|---|---|
| `function update_updated_at_column() does not exist` | Corregida migración — la función es `set_updated_at` en `public` |
| 0 filas en `agent_reasoning_events` | [PR #62](https://github.com/Auyan-ai/platform/pull/62): JSONB double encoding — pasar dict directo sin cast `$6::jsonb` |
| Hilo sin mensaje del agente al escalar | [PR #63](https://github.com/Auyan-ai/platform/pull/63): `response_text` obligatorio siempre |
| `asyncio.get_event_loop()` en Python 3.12 | [PR #60](https://github.com/Auyan-ai/platform/pull/60): `get_running_loop()` |

---

## Sesión 19 — Context engineering + KB seeding + multi-turno (2026-05-18)

- Análisis del artículo de Neil Rahilly (Sierra) contra el codebase
- `scripts/seed_kb.py` — KB de Lunaria con datos fantasiosos para anti-alucinación
  - Devoluciones: **49 días** (7 lunas llenas), reembolso en **Crédito Estelar**
  - Envío gratis desde **€137**, modalidades: **Constelación Express / Tránsito Lunar**
  - Tracking con código **LN-XXXXXXX** vía sistema **Órbita**
- Multi-turno validado: agente usó contexto del turno anterior correctamente ✅
- Alucinación detectada: tienda Shopify auto-generada como "Lunaria Boards" snowboards — conflicto con KB de joyería

---

## Sesiones 20-22 — Sprint 9

### Sprint 9.1 — Idempotency ([PR #68](https://github.com/Auyan-ai/platform/pull/68))

- Tabla `idempotency_keys` TTL 24h
- Header `X-Idempotency-Key` opcional en `/webhooks/inbound`
- Suite total: 510/510 (con 9.2)

### Sprint 9.2 — Skills L2 ([PR #69](https://github.com/Auyan-ai/platform/pull/69))

- `shopify.add_order_note`, `shopify.tag_order`
- Gate en `execute_skill`: L2 requiere `allow_l2_skills: true` en `extra`

### Sprint 9.3 — Audit log PII ([PR #71](https://github.com/Auyan-ai/platform/pull/71))

- Tabla `tenant_secrets` (salt PII) + `skill_audit_log`
- `services/pii.py` — email→`<email:hash16>`, phone→`***-1234`, name→`J. P.`
- `AuditLogger` fire-and-forget
- Suite total: 537/537

### Sprint 9.4 — AOP cache invalidation ([PR #73](https://github.com/Auyan-ai/platform/pull/73))

- `AopCacheListener` — conexión asyncpg dedicada, `LISTEN aop_cache_invalidated`
- Invalida cache en todos los workers via Postgres NOTIFY sin Redis
- Suite total: 549/549

### Sprint 9.5 — Nudges antes del cierre ([PR #74](https://github.com/Auyan-ai/platform/pull/74))

- Columna `nudged_at` en `conversations`
- Cleanup envía mensaje recordatorio antes del cierre por inactividad
- Suite total: 560/560

---

## Sprint 10 — Skills L3 + Human Approval Mode ([PR #75](https://github.com/Auyan-ai/platform/pull/75)) ✅

### Sub-PR 10.1 — tenant_tool_permissions + pending_approvals

- Tablas `tenant_tool_permissions` y `pending_approvals`
- Gate granular en `execute_skill`: L3 + `human_approval_required` → crea `pending_approval`

### Sub-PR 10.2 — 4 skills L3 Shopify

| Skill | Descripción |
|---|---|
| `shopify.cancel_order` | Cancela pedido |
| `shopify.update_shipping_address` | Actualiza dirección antes de despacho |
| `shopify.refund_partial` | Reembolso parcial |
| `shopify.start_return` | Inicia devolución |

### Sub-PR 10.3 — Router aprobaciones

- `GET/POST /approvals` — aprobar ejecuta skill L3 con creds del tenant
- `GET/PUT /tenants/me/tool-permissions`

### Sub-PR 10.4 — UI cola de aprobaciones

- `ApprovalQueue.tsx` con botones Aprobar/Rechazar, poll cada 10s

### Sub-PR 10.5 — 52 fixtures adversariales

- 4 skills L3 × 13 fixtures = 52 YAML en `evals/fixtures/`

**Suite total: 628/628 verde.**

---

## Sprint 11 — Slow Agent end-to-end ([PR #76](https://github.com/Auyan-ai/platform/pull/76)) ✅

**Objetivo:** LLM-as-judge post-mortem que analiza conversaciones y propone cambios a AOPs.

### Sub-PR 11.1 — Tablas + modelos

- `slow_agent_runs`, `conversation_judgments`, `improvement_proposals`

### Sub-PR 11.2 — transcript + judge

- `ConversationTranscript` + `build_transcript()` + `format_for_judge()`
- `judge_conversation()` two-step: Sonnet first → Opus si confidence < 0.7

### Sub-PR 11.3 — sampling + runner + CLI

- `filter_candidates()`: escaladas siempre + ~10% resueltas (SHA-256 determinístico)
- `run_slow_agent_for_tenant()`: caps duros (max 50 convs/run)
- CLI: `python -m scripts.run_slow_agent --tenant <uuid>`

### Sub-PR 11.4-11.6 — Router + UI

- `GET/POST /proposals` con approve (pre-fill editor AOP) y reject
- `ProposalQueue`, `ProposalDetail`, `ProposalMetrics` en dashboard
- Nav: "Mejoras propuestas ✨"

**Sprint 11 completado ✅** — CLI validado, dashboard verificado, PR mergeado.

---

## Rate Limiting y cost controls ✅

| Sub-PR | Qué incluye | PR |
|--------|-------------|-----|
| A.1 | `rate_limit_buckets` + `enforce_rate_limit` + gate en `/webhooks/inbound` | [#77](https://github.com/Auyan-ai/platform/pull/77) |
| A.2 | `tenant_usage_daily` + `record_tenant_usage` + gate `check_tenant_budget` | [#78](https://github.com/Auyan-ai/platform/pull/78) |
| A.3 | `max_inbound_messages_per_conversation` check + escalación automática | [#79](https://github.com/Auyan-ai/platform/pull/79) |
| A.4 | `GET /tenants/me/usage` + UI card de consumo | [#80](https://github.com/Auyan-ai/platform/pull/80) |
| Fixes | README + readiness probe + broken tests + `message_cap` zero guard | [#81](https://github.com/Auyan-ai/platform/pull/81) |

**Suite total: 711/711 verde.**

Fix CI: `get_settings()` se llamaba directo dentro del endpoint, bypassando `dependency_overrides` → fix con `SettingsDep = Annotated[object, Depends(get_settings)]`.

---

## Pivot 2026-05-22 — BPO → Managed AI Service

Ver `docs/auyan-master-context.md` para contexto completo.

### El cambio en una frase

**ANTES:** Auyan operaba como BPO — tenía agentes humanos internos que atendían tickets escalados.

**AHORA:** Auyan opera como **Managed AI Service** estilo Crescendo — el cliente mantiene SU equipo CX para escalados; Auyan es el equipo externo de **Agent Engineers** que configura, mantiene y optimiza el agente IA del cliente.

### Implicaciones operativas

| Antes | Ahora |
|---|---|
| Esposa atendía tickets BPO 8h/día | Esposa = **QA + Knowledge Management + Customer Success** |
| Chatwoot interno como inbox core | **Chatwoot opcional** — recomendamos Chatwoot Cloud al cliente |
| Rol `tenant_agent` (empleados del cliente) | **`tenant_agent` deprecado** — hard removal en Bloque 0 |
| Dashboard interno = inbox Chatwoot-style | Dashboard interno = **panel operativo cross-tenant** |
| Escalación → agente humano interno de Auyan | Escalación → **equipo CX del cliente** (vía push al helpdesk) |

### Posicionamiento técnico

**Producto Decagon/Sierra (uso interno) + entrega Crescendo (cliente).**

- Internamente: power tools tipo Duet/Agent Studio (editor AOPs, simulator, auto-gen, diagnostic tools, watchtower)
- El cliente: dashboard read-only + reportes proactivos + AIDE asignado + cero configuración técnica

### 25 decisiones cerradas del grill

| # | Área | Decisión |
|---|---|---|
| 1 | Modelo de negocio | Producto Decagon/Sierra interno + entrega Crescendo cliente |
| 2 | KB | 3 niveles: nunca/aporta/edita factual |
| 3 | Helpdesks | 4 adapters bidireccionales: Gorgias + Chatwoot + Zendesk + (Intercom reactivo) |
| 4 | Canales WhatsApp/IG/Widget | Heredados via helpdesk, NO construidos directamente |
| 5 | Chatwoot Cloud Paid | Recomendado al cliente sin helpdesk; cliente paga directo |
| 6 | Shadow mode | Internal notes en helpdesk del cliente |
| 7 | Activación gradual | Por categoría, decisión Auyan no cliente |
| 8 | Escalación | Mix por tenant: push helpdesk default, email fallback |
| 9 | Onboarding | 9 pasos self-serve + call con AIDE opcional |
| 10 | "Biblia" del cliente | `tenant_playbook` DB en repo, NO Notion |
| 11 | Reporte semanal | Email = resumen, dashboard = fuente completa |
| 12 | Dashboard cliente | 7 secciones MVP, "Conversaciones" → "Insights" estilo Decagon Explorer |
| 13 | AI Data Assistant cliente | Bloque 2, NO MVP |
| 14 | Dashboard super_admin | Nav 2 niveles + Home Review Queue filtrado por rol |
| 15 | Roles internos | Estructura DB desde día 1, ambos super_admin hasta mes 9-10 |
| 16 | Simulator | Bloque 0 MVP (manual + judge 4 dims), Bloque 2 auto-gen, Bloque 3 canary |
| 17 | 4 dimensiones judge | Reasoning / Knowledge / Tools / Brand voice |
| 18 | Tipos de test | Unit / Integration / Simulation |
| 19 | AOPs steps[] | Preparación Bloque 0 (datos para Bloque 2 Flow Analysis) |
| 20 | tenant_agent | Hard removal en Bloque 0 |
| 21 | Pricing/billing | Stripe Bloque 2 (no MVP), primer 1-2 clientes manual |
| 22 | Landing | `apps/landing` + Aceternity UI (no Tailwind UI) |
| 23 | Design Sprint | 1-2 semanas al inicio de Bloque 1 |
| 24 | Iteración rápida | DB editable lo que itera con cliente, code-side lo demás |
| 25 | Fase 0 legal | En paralelo con Bloque 0 técnico |
