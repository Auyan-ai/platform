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

---

## Bloque 0 — Sanity check + fundación arquitectónica ✅

Periodo post-pivot inmediato para dejar el stack coherente con el modelo Managed AI Service antes de construir Bloque 1.

| # | Foco | Resultado |
|---|---|---|
| 0.1 | Hard removal `tenant_agent` | ✅ [PR #83](https://github.com/Auyan-ai/platform/pull/83)+[#84](https://github.com/Auyan-ai/platform/pull/84) |
| 0.2 | Framework adapters base | ✅ [PR #87](https://github.com/Auyan-ai/platform/pull/87) |
| 0.3 | ShopifyAdapter stateless | ✅ [PR #89](https://github.com/Auyan-ai/platform/pull/89) |
| 0.4 | ChatwootAdapter stateless + webhook | ✅ [PR #90](https://github.com/Auyan-ai/platform/pull/90) |
| 0.5 | ZendeskAdapter + OAuth flow + webhook | ✅ [PR #91](https://github.com/Auyan-ai/platform/pull/91) |
| 0.6 | GorgiasAdapter + OAuth flow + webhook | ✅ [PR #92](https://github.com/Auyan-ai/platform/pull/92) |
| 0.7 | PostmarkEmailAdapter + EmailSender | ✅ [PR #93](https://github.com/Auyan-ai/platform/pull/93) |
| 0.8 | Roles internos DB | ✅ [PR #94](https://github.com/Auyan-ai/platform/pull/94) |
| 0.9 | AOPs `steps[]` opcional + events | ✅ [PR #95](https://github.com/Auyan-ai/platform/pull/95) |
| 0.10 | Simulator MVP + UI | ✅ [PR #96](https://github.com/Auyan-ai/platform/pull/96)+[#97](https://github.com/Auyan-ai/platform/pull/97) |

### Notas clave

- `tenant_agent` fue eliminado del modelo: quedan `super_admin` y `tenant_admin`.
- Las integraciones de helpdesk/commerce pasan a adapters stateless por tenant: Shopify, Chatwoot, Zendesk y Gorgias.
- Postmark quedó como servicio global Auyan→cliente, no como integración bidireccional por tenant.
- Roles internos (`internal_users`, `tenant_assignments`, `role_permissions`) quedaron listos para filtrar Home/Review Queue por rol.
- AOPs `steps[]` emiten `step_entered`/`step_completed`, acumulando datos desde el inicio para Flow Analysis en Bloque 2.
- Simulator MVP corre el grafo real contra conversaciones sintéticas, con judge 4 dimensiones y assertions programáticas. Checkpoint E2E aprobado: CE-01 9.5/10 y RE-01 7.5/10.

### Bloque 0.11 — Validación E2E parcial

La validación completa de 25 scenarios quedó bloqueada por crédito Anthropic. Antes del bloqueo se arreglaron bugs deterministas offline:

1. Fixture DE-04 de `update_shipping_address` sin `id`.
2. Scenario CE-05 insatisfacible sin número de pedido.
3. Harness `must_escalate: False` ignorado.
4. Inyección de fecha actual en system prompt.
5. Guardrails de CE-02 para no escalar solo por impaciencia.

Pendiente vivo: reseed AOPs, corrida `--reseed --no-judge --all`, fixes restantes y corrida final con judge cuando haya crédito.

---

## Bloque 1 — Sprint A completado hasta Sub-PR 1.9 ✅

### 1.0 — Design Sprint + shell visual

- `docs/DESIGN.md` v1.2 aprobado para Bloque 1.
- Dashboard movido hacia composición Mercury light: shell claro, sidebar fija de 200px, iconos de 14px, topbar no fija, tarjetas densas con sombra sutil.
- Base visual lista para cliente e interno.

### 1.1 + 1.2 — `tenant_playbook` + `tenant_facts` ✅

| Archivo | Qué se hizo |
|---|---|
| `supabase/migrations/20260525000001_add_tenant_playbook.sql` | Tabla `tenant_playbook` con 5 secciones markdown: brand_voice, product_overview, policies, escalation_notes, agent_instructions. |
| `supabase/migrations/20260525000002_add_tenant_facts.sql` | Tabla `tenant_facts` JSONB editable por tenant_admin. |
| `db/models.py` | `TenantPlaybook` + `TenantFacts`. |
| `db/queries.py` | `get/upsert_tenant_playbook`, `update_tenant_playbook_section`, `get/upsert_tenant_facts`. |
| `agents/nodes/load_tenant_context.py` | Carga playbook/facts para el grafo. |
| `aops/compiler.py` | Render de facts/playbook dentro del system prompt. |
| `routers/tenants.py` | `GET/PUT /tenants/me/playbook` + `GET/PUT /tenants/me/facts`. |
| `apps/web/components/tenant-context/*` | Editor interno de playbook + form cliente de facts. |

Diseño:

- `tenant_playbook` lo edita Auyan y se inyecta como `## Conocimiento de la Marca`.
- `tenant_facts` lo edita el cliente y se inyecta como `## Datos del cliente`.
- Si el tenant no tiene datos, los bloques se omiten sin error.

Verificación sesión 41: `tests/test_tenants.py` 16/16 verde, suite API 990/990 verde, ruff limpio, typecheck web verde, lint de archivos tocados verde.

### 1.3 — Onboarding wizard + lifecycle ✅

Mergeado en [PR #102](https://github.com/Auyan-ai/platform/pull/102).

| Archivo | Qué se hizo |
|---|---|
| `supabase/migrations/20260527000001_add_tenant_onboarding.sql` | `agent_lifecycle_state` en `tenants` + tabla `tenant_onboarding`. |
| `db/models.py` | `AgentLifecycleState` + `TenantOnboarding`. |
| `db/queries.py` | `get/upsert/submit_tenant_onboarding` + `update_tenant_lifecycle_state`. |
| `routers/tenants.py` | `GET/PUT /tenants/me/onboarding`, `POST /tenants/me/onboarding/submit`, `PUT /tenants/me/lifecycle`. |
| `apps/web/components/onboarding/OnboardingWizard.tsx` | Wizard cliente de 9 pasos con guardado incremental, progreso y submit. |
| `apps/web/app/clients/[tenantId]/onboarding/page.tsx` | Nueva página cliente `/clients/[tenantId]/onboarding`. |
| `apps/web/components/clients/ClientSidebar.tsx` | Link cliente a Onboarding. |

Diseño:

- Lifecycle hardcoded: `initial → discovery → building → shadow → ramping → active`, con `paused/churned` para operación.
- Submit del wizard mueve el tenant a `building`.
- Comunicación email usa `EmailSender.send_email`; sin Postmark configurado hace no-op y no bloquea el flujo.
- `step_data` guarda intake bruto por paso (`"1"`..`"9"`). La curación a playbook/KB se hace en pasos posteriores.

Verificación sesión 42: ruff limpio en API tocada, `tests/test_tenants.py` 19/19 verde, suite API 993/993 verde, typecheck monorepo verde, Biome limpio en archivos web tocados. `pnpm --filter @auyan/web lint` completo seguía fallando por deuda previa en archivos no tocados.

QA manual 2026-05-28: onboarding probado en la sección cliente y funcionando correctamente.

### 1.4 — KB drop-zone + pending review ✅

Implementado en rama `codex/bloque-1-kb-dropzone`.

| Archivo | Qué se hizo |
|---|---|
| `supabase/migrations/20260528000001_add_tenant_knowledge_submissions.sql` | Tabla `tenant_knowledge_submissions` + enums de source/status + RLS super_admin/tenant_admin. |
| `db/models.py` | `TenantKnowledgeSubmission` + tipos `TenantKnowledgeSourceType` y `TenantKnowledgeSubmissionStatus`. |
| `db/queries.py` | CRUD de submissions, approve/reject y creación de `knowledge_base_documents`/`knowledge_base_chunks`. |
| `services/knowledge_ingestion.py` | Chunking simple por palabras + embeddings por chunk usando OpenAI embeddings. |
| `routers/tenants.py` | `GET/POST /tenants/me/kb-submissions`, `POST /approve`, `POST /reject`. |
| `apps/web/components/knowledge/KnowledgeDropZone.tsx` | Pantalla cliente para aportar contenido, URL o archivo de texto/markdown leído client-side. |
| `apps/web/components/knowledge/KnowledgeReviewQueue.tsx` | Cola interna pending review para aprobar/indexar o rechazar. |
| `apps/web/app/clients/[tenantId]/knowledge/page.tsx` | Ruta cliente `/clients/[tenantId]/knowledge`. |
| `apps/web/app/(dashboard)/tenants/[tenantId]/knowledge/page.tsx` | Ruta interna `/tenants/[tenantId]/knowledge`. |
| `packages/shared/src/api-types.ts` | Tipos OpenAPI regenerados. |

Diseño:

- Cliente puede crear submissions `pending_review` con texto, URL o archivo textual.
- Super_admin revisa la cola; aprobar genera chunks, embeddings y documento RAG.
- Rechazar deja trazabilidad con `review_note`.
- No se mete Supabase Storage todavía; PDFs/binarios quedan para una iteración posterior.

Verificación sesión 43: `tests/test_tenants.py` 24/24 verde, suite API 998/998 verde, ruff limpio en archivos tocados, Biome limpio en archivos web tocados, `pnpm typecheck` verde y `pnpm build:web` verde.

### 1.5 — Reporte semanal automatizado ✅

Implementado en cuatro PRs pequeños, verificados y mergeados secuencialmente:

| PR | Qué se hizo |
|---|---|
| [#104](https://github.com/Auyan-ai/platform/pull/104) | Tabla `weekly_reports`, modelos, queries y endpoints para listar, generar, editar, enviar a revisión y aprobar drafts semanales. |
| [#105](https://github.com/Auyan-ai/platform/pull/105) | Envío Postmark del reporte aprobado, template HTML/texto, tracking `sent/failed` y manejo de errores de entrega. |
| [#106](https://github.com/Auyan-ai/platform/pull/106) | Consola interna de revisión, historial/vista cliente de reportes y tipos OpenAPI regenerados. |
| [#107](https://github.com/Auyan-ai/platform/pull/107) | Script `scripts.generate_weekly_reports` y GitHub Actions semanal para crear drafts del lunes a partir de la semana anterior. |

Diseño:

- Email semanal = resumen ejecutivo; dashboard cliente = fuente completa.
- Auyan debe aprobar antes de enviar; el cliente sólo ve historial y reportes enviados.
- UI sigue el shell Mercury light de `docs/DESIGN.md`, sin abrir AI Data Assistant ni visualizaciones de Bloque 2.
- El workflow programado queda listo para GitHub Actions; requiere `DATABASE_URL` como secret antes de correr contra staging/producción.

Verificación sesión 44: ruff limpio, suite API 1013/1013 verde, `pnpm --filter @auyan/web typecheck` verde, `pnpm build:web` verde y CI verde en PRs #104–#107. El lint web completo sigue teniendo deuda previa en archivos no tocados.

### 1.6 — Dashboard cliente 7 secciones MVP ✅

Implementado en cinco PRs pequeños, verificados y mergeados secuencialmente; luego recibió mejoras menores en Home cliente:

| PR | Qué se hizo |
|---|---|
| [#109](https://github.com/Auyan-ai/platform/pull/109) | Shell cliente de 7 secciones: Home, Insights, Reportes, Knowledge Base, Aprobaciones, Onboarding y Configuración. |
| [#110](https://github.com/Auyan-ai/platform/pull/110) | Home con lifecycle phase, headline de reporte semanal, heatmap de actividad y alertas. |
| [#111](https://github.com/Auyan-ai/platform/pull/111) | Endpoint `/tenants/me/insights` + Explorer cliente con heatmap, donut de intents, breakdowns y drill-down con reasoning panel. |
| [#112](https://github.com/Auyan-ai/platform/pull/112) | Knowledge Base consolidada con drop-zone, `tenant_facts` y estado de procesamiento/revisión. |
| [#113](https://github.com/Auyan-ai/platform/pull/113) | Onboarding auto-hide al salir de fase `initial` y redirect de acceso directo. |
| [#152](https://github.com/Auyan-ai/platform/pull/152) | Home cliente: lifecycle phase pasa de badge ambiguo a stepper compacto con fase actual en cobalto, fases completadas con icono outline estilo sidebar y estado final `Active` colapsado. |
| [#154](https://github.com/Auyan-ai/platform/pull/154) | Home cliente: `Resolución IA` deja de ser mock estático y pasa a usar series por ventana (30d, 7d, 24h), tooltip por bucket y selector temporal minimalista. |

Diseño:

- Sidebar cliente queda alineada a `auyan-master-context.md`: Home/Insights/Reportes/Knowledge Base/Aprobaciones/Onboarding/Configuración.
- `Conversaciones` pasa a `Insights`; las URLs antiguas redirigen y el drill-down mantiene lectura con PII masked.
- Lifecycle en Home usa el acento cobalto de `docs/DESIGN.md`; no usa verde para `Active` ni tacha/elimina fases anteriores.
- `Resolución IA` usa cobalto sólo para la serie principal, warning para escalación, fondo blanco y selector temporal neutro.
- AI Data Assistant, Facturación y visualizaciones avanzadas siguen fuera del MVP y pertenecen a Bloque 2.
- Configuración es read-only para cliente: integraciones conectadas, branding operativo y perfil AIDE.

Verificación sesión 45: typecheck web verde, `pnpm build:web` verde y CI verde en PRs #109–#113. Para #111 además `poetry run ruff check` y `pytest tests/test_tenants.py` verdes. Para #154: ruff focal, tests de métricas 3/3, Biome focal, typecheck web, build web y `git diff --check` verdes.

### 1.7 — Dashboard super_admin Home/Review Queue ✅

Implementado en [PR #115](https://github.com/Auyan-ai/platform/pull/115).

Qué incluye:

- Endpoint super_admin `GET /tenants/admin/review-queue` con pendientes cross-tenant.
- Home interno reemplazado por Review Queue con filtros de foco por rol: Todos, QA-KM, AIDE y Ops.
- Pendientes agregados por tenant: KB pending review, weekly reports pending review, L3 approvals y improvement proposals.
- Links directos a las pantallas scoped del tenant para operar cada pendiente.
- Tipos OpenAPI regenerados.

Verificación sesión 46: `poetry run ruff check`, `pytest tests/test_tenants.py`, `pnpm --filter @auyan/web typecheck`, Biome focal, `pnpm build:web` y CI verdes.

### 1.8 — Landing pública ✅

Implementado en [PR #117](https://github.com/Auyan-ai/platform/pull/117).

Qué incluye:

- App pública separada `apps/landing` sobre Next.js App Router.
- Home de primer viewport para Auyan como Managed AI Service de CX e-commerce, no SaaS self-serve.
- Páginas públicas `/pricing`, `/founding-partner`, `/security`, `/about` y `/blog`.
- Componentes visuales con Framer Motion y composición alineada al sistema Mercury light.
- Plausible preparado vía `NEXT_PUBLIC_PLAUSIBLE_DOMAIN`.
- Scripts raíz `dev:landing` y `build:landing`, más ignores para output local de la app.

Verificación sesión 47: `pnpm --filter @auyan/landing typecheck`, `pnpm build:landing`, `pnpm typecheck`, Biome focal, `git diff --check` y CI verdes.

### 1.9 — Email outbound general ✅

Implementado en PRs pequeños, verificados y mergeados secuencialmente:

| PR | Qué se hizo |
|---|---|
| [#119](https://github.com/Auyan-ai/platform/pull/119) | Tablas `outbound_email_templates` y `outbound_email_jobs`, modelos, queries, endpoints super_admin y tipos OpenAPI regenerados. |
| [#120](https://github.com/Auyan-ai/platform/pull/120) | Dispatcher de cola con claim due, envío Postmark, `sent`, retry/backoff exponencial y script `scripts.dispatch_outbound_email`. |
| [#121](https://github.com/Auyan-ai/platform/pull/121) | Consola interna `/tenants/[tenantId]/emails` para templates, encolar jobs y revisar estado/fallos recientes. |

Diseño:

- Templates y jobs son tenant-scoped; sólo super_admin opera creación/edición/encolado desde UI interna.
- El worker no reclama jobs si falta `POSTMARK_API_TOKEN`, para no consumir intentos en local/staging mal configurado.
- La cola usa `idempotency_key`, `attempts`, `max_attempts`, `next_attempt_at`, `postmark_message_id` y `error`.
- La UI queda en el sidebar interno como `Emails`; no se expone al dashboard cliente.

Verificación sesión 48: `poetry run ruff check`, suite API 1026/1026 verde, `pnpm typecheck`, `pnpm build:web`, Biome focal, `git diff --check` y CI verdes.

---

## Sesión 50 — Limpieza de `progress` + staging DB desbloqueado ✅

Se limpió `docs/progress.md` para quitar información operativa ya obsoleta y evitar dos focos paralelos.

Cambios archivados:

- Las migraciones de Bloque 1 dejaron de aparecer como pendiente activo porque ya fueron aplicadas en staging.
- El Bloque 0.11 se reencuadró desde una validación E2E básica bloqueada por crédito hacia una verificación madura del agente en staging.
- Billing manual 1.10 queda documentado como pendiente por inputs externos, pero no como foco activo.
- Chatwoot queda definido como primer helpdesk real para la verificación; Zendesk y Gorgias siguen pendientes posteriores.

Migraciones confirmadas como desbloqueadas:

| Migración | Incluye |
|---|---|
| `20260525000001_add_tenant_playbook.sql` | `tenant_playbook` |
| `20260525000002_add_tenant_facts.sql` | `tenant_facts` |
| `20260527000001_add_tenant_onboarding.sql` | `agent_lifecycle_state` + `tenant_onboarding` |
| `20260528000001_add_tenant_knowledge_submissions.sql` | `tenant_knowledge_submissions` + cola KB |
| `20260528000002_add_weekly_reports.sql` | `weekly_reports` + flujo `draft/pending_review/approved/sent/failed` |
| `20260528000003_add_outbound_email_queue.sql` | `outbound_email_templates` + `outbound_email_jobs` |

---

## Sesión 59 — Bug suelto: cierre externo de tickets helpdesk ✅

Implementado en [PR #157](https://github.com/Auyan-ai/platform/pull/157).

Contexto:

- Este trabajo fue una mejora puntual fuera del plan activo de `progress.md`.
- El agente y los operadores podían responder, escalar y cerrar internamente, pero el ticket externo en Zendesk/Gorgias/Chatwoot podía quedar abierto.
- No se tocó el grafo, AOPs ni la decisión automática `respond/resolve/escalate`; eso queda para una sesión separada.

Qué se hizo:

- `POST /conversations/{conversation_id}/close` ahora intenta sincronizar el cierre externo antes de marcar la conversación interna como `closed`.
- Mapeo de estados externo:
  - Zendesk → `solved`
  - Gorgias → `closed`
  - Chatwoot → `resolved`
- Si el cierre externo falla, el API devuelve `502` con `external_helpdesk_close_failed` y no finge cierre interno exitoso.
- Chatwoot pasa a usar el endpoint oficial `toggle_status` para resolver conversaciones.
- Se añadió `gorgias` como `ChannelType` real en backend/shared/web y migración Supabase `20260602000001_add_gorgias_channel.sql`, porque Gorgias ya tenía OAuth/webhook/adapter pero no podía persistirse como canal de conversación.

Verificación:

- `poetry run pytest` → 1117 tests verdes.
- `pnpm typecheck` verde.
- `poetry run ruff check` focal verde.

Notas:

- La migración debe aplicarse manualmente en Supabase/Railway siguiendo la regla del proyecto: Railway despliega código pero no aplica SQL.
- Queda fuera de este PR la decisión automática del agente sobre cuándo cerrar/resolver un ticket.
