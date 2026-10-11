# Auyan — Archivo histórico de progreso

> ⚠️ **DOC HISTÓRICO — solo registro.** Nada de este archivo es estado vigente ni fuente de verdad;
> no usarlo para decisiones ni implementación actual. El estado activo del proyecto vive en
> [`progress.md`](progress.md); la verdad técnica vive en el código + tests.
> Contiene: Sprints 0-11, rate limiting, el pivot de 2026-05-22, Bloques 0-1, y las secciones
> compactadas de `progress.md` (limpieza 2026-07-17).

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

---

# ═══ Material archivado el 2026-07-17 (compactación de progress.md) ═══

> Secciones movidas desde `docs/progress.md` durante la limpieza documental.
> Todo lo de abajo está CERRADO o SUPERADO; no usar como estado vigente.

## Cabeceras de sesiones 59-79

> _Sesión 79 (2026-09-30) — **Planificación del Sprint 2 (WhatsApp vía Zernio), solo docs, con Opus.** La API de Zernio se verificó en su OpenAPI (SDK oficial `zernio-dev/zernio-php`; `docs.zernio.com` bloqueado desde el contenedor). Hallazgos que cambian el diseño: el teléfono puede no llegar (**BSUID** de Meta desde abril de 2026); el código asumía `channel == helpdesk` en entrega, aprobaciones, escalado y cierre (`reply_delivered` daba por entregado cualquier canal no-helpdesk); un chat de WhatsApp no termina (hacen falta **sesiones**); los nudges de 48 h caerían fuera de la **ventana de 24 h**; `agent_human` exige un usuario de Auyan. Decisiones con Kenny: una cuenta Zernio de Auyan con **profile + API key limitada por tenant**; **handoff modular** (`HandoffTarget`, Zendesk primero) + silencio de la IA 12 h si la marca contesta desde el móvil (coexistence); fuera de ventana, **patrón del sector** (plantilla de re-enganche + entrega diferida); **transcribir notas de voz ya** (proveedor por mini-benchmark en C0); fotos a Storage y adjuntas al ticket; L3 por email **o** teléfono del pedido, si no → bloquear y ofrecer escalar (**OTP → backlog post-piloto**); sesión nueva si la anterior cerró o se resolvió hace >7 días; sin nudges en WhatsApp; E2E con sandbox y luego número real. [ADR 0010](adr/0010-whatsapp-zernio-handoff.md) (Propuesta) + [plan por PRs](whatsapp-zernio-plan.md). Implementación con Sonnet._

> _Sesión 78 (2026-09-30) — **Sprint 1 (bloque A) cerrado en lo que depende del código; queda A4 en vivo con Kenny.** **#260 + A2 #2:** los webhooks de Zendesk, Gorgias y Chatwoot ya no corren el grafo en el request: validan, reclaman la idempotencia, persisten y encolan en **una transacción** (`inbound_jobs`) → 200 en ~0,3–1,2 s. Un **worker en proceso** (lifespan) reclama por conversación con **advisory lock**: nunca hay dos turnos a la vez; las ráfagas se unen en una sola respuesta; hay heartbeat, recuperación tras crash, release en shutdown y reintentos con backoff ([ADR 0008](adr/0008-inbound-queue-postgres.md)). **A3 en vivo sobre Zendesk:** webhook duplicado ✅, ráfaga/simultáneos ✅ (sin solapes), credencial mala ✅ (`respond:undelivered`, sin resolver ni cobrar), trace LangSmith↔Supabase sin PII ✅. Bugs que salieron solo en vivo: carrera en el intake (`uq_end_customers_email` → 500), historial que terminaba en el agente (→ `error`), re-saludo, **el finalize de LangSmith pisaba `tenant_id`/`conversation_id` (ningún run correlacionaba)**, email/teléfono del cliente llegaban tal cual a LangSmith (ahora se enmascaran), e idempotencia en **409 permanente** tras un fallo (soft-delete no liberaba el `unique`). **A4 (preparación):** `refund_partial` mandaba `parent_id` nulo (Shopify lo rechaza) y `start_return` llamaba a un recurso REST que **no existe** → reescritos (transacción padre / GraphQL `returnCreate`). Gorgias estaba apuntando a Railway (reapuntado a Cloud Run). Tests de la cola contra **Postgres real** (`AUYAN_TEST_DATABASE_URL`). A4 11/11 en vivo con 5 bugs de Shopify/grafo corregidos. Sin mergear: rama `feature/sprint1-webhook-queue` ([PR #264](https://github.com/Auyan-ai/platform/pull/264)).)_

> _Sesión 77 (2026-09-29/30) — **E2E en vivo de Zendesk + migración de staging a Cloud Run/Vercel + seguridad L3. 14 PRs mergeados ([#247](https://github.com/Auyan-ai/platform/pull/247)–[#259](https://github.com/Auyan-ai/platform/pull/259)) + [#261](https://github.com/Auyan-ai/platform/pull/261) abierto.** Railway se quedó sin crédito → **API en Google Cloud Run** (`europe-west3`, junto al pooler de Supabase `eu-central-1`; secretos en Secret Manager; `apps/api/scripts/deploy_cloud_run.sh`) y **dashboard en Vercel** (#251). Supabase staging estaba **pausado** (free tier) → restaurado. **Zendesk E2E en vivo** sobre Marea: 7 bugs que nunca se habrían visto sin tráfico real — API tokens retirados por Zendesk → OAuth `client_credentials` (#247); un stub en `routers/webhooks.py` **tapaba el webhook real** (#250); idempotencia por ticket (solo 1er mensaje) + anti-loop (#248); placeholder inexistente y **JSON roto por texto sin escapar** → el Trigger manda solo IDs y el comentario se lee de la API (#252). Auditoría s71 #3 cerrada: **solo se resuelve/cobra tras confirmar la entrega outbound** (#249). **Escalación L3 se cierra sola** tras aprobar/rechazar (#253). Mini-sprint UX (#254): dirección actual solo al dueño del pedido, limpieza de firmas/`&nbsp;`, confirmación con la dirección nueva, `address2`. **🔴 Bug crítico** `upsert_tool_permission` fallaba SIEMPRE (tipo ambiguo `$6`) → no se podían crear tenants ni cambiar permisos (#255). **🔴 Hueco de seguridad:** se podía modificar un pedido ajeno sabiendo solo el número → **gate de ownership en código** para toda L3 sobre pedido (#259). #261: el supervisor no veía la salida de las skills (rechazaba respuestas correctas y escalaba) + saludo en la 1ª respuesta. Investigación de verificación de identidad (Decagon/Sierra/Intercom/Chatbase/Gorgias) → issues #256–#258, #260. Kenny compró el dominio **`auyan.es`**. **Zernio/WhatsApp pasa a prioridad** (la mayoría de marcas en España usan WhatsApp).)_

> _Sesión 76 (2026-09-29) — **Planificación pre-piloto (solo docs, cero código).** Kenny define 3 frentes antes de firmar el primer piloto, en este orden: **A) E2E de integraciones** (piloto más probable sobre **Zendesk**, el único helpdesk sin E2E en vivo), **B) JEV** (clasificador tipado de TypeSafe, lanzado 2026-09-15) en `select_aop` en **shadow mode** primero, **C) Zernio** (API unificada de mensajería/redes, WhatsApp incluido) — **spike de descubrimiento a fondo** antes de diseñar; decisión tomada: los escalados de WhatsApp van por **handoff al helpdesk del cliente**. Plan detallado en "🚀 Empezar aquí — Plan pre-piloto" abajo. Implementación en sesiones siguientes._

> _Sesión 73 (2026-06-27) — **LangSmith node-level tracing + fix crítico de seguridad.** Antes los traces de LangSmith solo mostraban `agent_conversation` → `agent_model_call` (tokens/costo agregados); el detalle nodo-por-nodo del grafo (select_aop, reason, execute_skill, supervise…) solo vivía en el dashboard de "Agent reasoning" (Supabase `reasoning_events`). [#237](https://github.com/Auyan-ai/platform/pull/237) MERGEADO: wrapper genérico `_traced` en `build_graph` emite un child run (`run_type=chain`) por cada nodo del grafo con nombre, duración y outputs allowlisteados — cero cambios en los nodos; `record_node_run` en `LangSmithClient`+`ObservabilityClient`; trace propagado vía `AgentState._trace_run_id/_trace_dotted_order` y `observability` en `AgentDependencies`. **🔴 Fix de seguridad [#238](https://github.com/Auyan-ai/platform/pull/238) MERGEADO (Kenny lo cazó en review):** el wrapper original mandaba el dict de output COMPLETO de los nodos sin allowlist a LangSmith (SaaS de terceros) → filtraba el **access token de Shopify descifrado** (`load_tenant_context.commerce_integration_ctx.credentials.token`) y **PII** (`load_conversation.conversation_history`/`end_customer`). El #237 alcanzó a mergearse y deployar con el leak antes del fix → el token estuvo en traces de los webhooks de prueba de hoy. Fix: **allowlist estricta** (`_NODE_OUTPUT_KEYS.get(name, [])` → nodo sin entrada emite `{}`, solo timing del span) + **redacción recursiva defensiva** (`_redact_dict` tacha token/credentials/secret/api_key/password/authorization) + 6 tests de regresión en `test_graph_tracing.py` (uno prueba que el token jamás aparece en el payload). 1323 verde, ruff/mypy limpios. **Verificado EN VIVO sobre Marea** (trace `f21ab9a7…`): child runs presentes, `execute_skill` muestra el tool call de Shopify, `load_tenant_context`/`load_conversation` sin credenciales ni PII. **🔴 PENDIENTE: rotar el access token de Shopify de Marea** (estuvo expuesto en LangSmith entre #237 y #238) → regenerar en Shopify + re-registrar con `railway run … configure_staging_integrations`. Aprendizaje guardado en memoria [[feedback_observability_no_secrets]]: observabilidad nunca exfiltra secrets/PII — allowlist, no denylist._

> _Sesión 74 (2026-06-27) — **ADRs de arquitectura + case study para portafolio.** Kenny va a usar el proyecto como portafolio (target: roles freelance). Creado `docs/adr/` con 7 ADRs en formato Nygard (Contexto → Decisión → Alternativas → Consecuencias): [0001] multi-tenant `tenant_id`+RLS, [0002] modelo de negocio Managed AI Service, [0003] agente como grafo LangGraph, [0004] AOPs editables en runtime, [0005] skills L1/L2/L3 + approval, [0006] LangSmith observabilidad, [0007] model routing por tarea. Más `docs/case-study-auyan.md`: writeup narrativo para la web con ángulo founder/cliente/inversor, cada decisión enlaza a su ADR. Cumple lo que CLAUDE.md ya prometía (`docs/adr/`); `CONTEXT.md` sigue pendiente. **Solo docs — cero código, cero secrets/PII.** PR aparte contra `develop`. Sesión 73 abajo.)_

> _Sesión 72 (2026-06-21) — **Sesión autónoma: 3 PRs MERGEADOS (Zendesk managed-auth, latencia del AOP returns, motor de Billing Bloque 2), suite 1306 verde.** Kenny pidió cerrar los 3 pendientes técnicos dejándole solo Customer Discovery; lo manual quedó en "Arranque sesión 73". [#232](https://github.com/Auyan-ai/platform/pull/232) **Zendesk dual-auth** (API token/Basic, espejo de la s69 de Gorgias) + provider `zendesk` en `configure_staging_integrations`: el enum `channel_type` ya tenía `zendesk` → **sin migración**; el outbound usa el shape estándar (`add_comment` público), **sin** la rareza `source.type`/`body_html` de Gorgias. [#233](https://github.com/Auyan-ai/platform/pull/233) **latencia HOPS por prompt**: el AOP `returns` ahora secuencia "el dato va primero, la afirmación después" (verificar la política en KB/`tenant_facts`/`get_shop_policies` ANTES de afirmar un plazo) → mata de raíz el reject+retry del supervisor; test de invariante en `test_canonical_aops`. [#234](https://github.com/Auyan-ai/platform/pull/234) **motor de Billing Bloque 2** (PRD §7 puntos 1+3): migración `resolution_events` (append-only) + `billing_subscriptions` (snapshot de floor/included/overage, RLS solo-lectura, campos `stripe_*` nullable), conteo por periodo mensual anclado con **ventana de reapertura** (§2.3), catálogo de tiers (números **PROVISIONALES**), `compute_period_usage`, hooks en `respond`/`reopen`, y `GET /billing/usage` + `PUT /billing/subscription`. **Stripe NO entró** (necesita key + dashboard → siguiente trozo aditivo). Suite **1306 verde**, ruff/mypy limpios. **#232/#233/#234 MERGEADOS.** **🔴 Pendiente: aplicar a mano las migraciones de billing (#234) + la del piso L3 (#231) + `add_gorgias_channel` en prod** (Railway no corre SQL). Ver "🚀 Arranque sesión 73" abajo.)_

> _Sesión 71 — **Auditoría de robustez del grafo + cierre del hallazgo 🔴 L3-sin-approval (Opción B, 2 PRs TDD).** Re-auditoría 12-capas: núcleo sólido (`tool_choice` code-gated, `@guarded`, degradación elegante, prompt caching, anti-inyección RAG); el riesgo vive en los bordes. **🔴 Hallazgo:** una L3 destructiva con `is_enabled=True`+`human_approval_required=False` se ejecutaba SIN aprobación humana, confiando solo en el supervisor (sesgado a APROBAR) — el seed de Marea tenía `start_return`/`update_shipping_address` así. **Raíz:** `human_approval_required=False` era ambiguo (opt-out consciente vs default de fábrica), fail-open en schema/función/runtime. **PR1 (piso):** `_l3_requires_human_approval` en `execute_skill` (L3 exige approval salvo opt-out RECONOCIDO) + migración `l3_autonomy_acknowledged_at/_by` (NULL=fail-safe, sin backfill → Marea cae del lado seguro sola) + señal propagada modelo→query→`load_tenant_context`. **PR2 (flexibilidad B):** endpoint rechaza 422 si se desactiva el approval de una L3 sin `acknowledge_l3_autonomy=true`; `upsert` sella/limpia el acknowledgment. **1297 tests verde, ruff limpio.** **PENDIENTE BLOQUEANTE: aplicar la migración a staging a mano ANTES del deploy** (Railway no corre SQL → si no, `load_tenant_context` hace SELECT de columnas inexistentes y escala todos los turnos). **Backlog de la auditoría:** #2 race de concurrencia (sin lock por conversación; la idempotencia es por `message_id`, no serializa 2 mensajes distintos), #3 entrega outbound best-effort tras marcar resuelto/cerrar ticket. Ver "🚀 Arranque sesión 73" abajo.)_

> _Sesión 70 — **Latencia de HOPS — 3 palancas, 2 PRs, validadas EN VIVO con traces (medir > adivinar).** Atacada la palanca de HOPS (turnos con supervisor encadenan llamadas LLM secuenciales; el peor caso s68 fue 3 reason + 2 supervise ≈ 20s). [#228](https://github.com/Auyan-ai/platform/pull/228): **P1 — el retry del supervisor ya no rompe el caché** (el feedback del reject se concatenaba al `system_prompt`, que vive en el bloque `cache_control` de #211 → el `reason#3` del retry hacía cache-miss total; ahora va en `state.supervisor_feedback` → `reason` lo inyecta como bloque dinámico NO cacheado; el prefijo queda bit-idéntico y el retry recupera el cache hit) + **P2 — calibración del supervisor** (sesgo por defecto a APROBAR, "red de seguridad no editor de estilo"; materialidad: un reject tactical debe nombrar la corrección concreta o aprueba). [#229](https://github.com/Auyan-ai/platform/pull/229): **P3 — no supervisar lecturas L1 intermedias** (en AOPs con `require_supervision`, `needs_supervision` mandaba a supervise la INTENCIÓN de leer una tool L1 como `get_shop_policies`; ahora con tool pendiente el único criterio es el tier L2/L3 — las mutaciones y el respond final se siguen supervisando). **VALIDADO EN VIVO (Marea staging, traces en `agent_reasoning_events`):** P1 confirmado — el `reason#3` del retry leyó `cache_r=2986` (antes 0). P3 confirmado comparando el MISMO turno de devoluciones antes vs después: `get_shop_policies` pasó de `tool_call → supervise → approve → result` (7 hops, 3 supervise) a `tool_call → result` directo (**6 hops, 2 supervise**). **Hallazgo de método:** P3 se descubrió mirando el trace, NO P2 — el reject del supervisor era LEGÍTIMO (afirmaba plazo de 30 días sin verificar con `get_shop_policies`); la palanca real era estructural. #228 y #229 MERGEADOS. **Ver "🚀 Arranque sesión 71" abajo.**)_
> _Sesión 69 — **Gorgias verificado E2E sobre Marea — Basic auth + 3 bugs del dogfood.** Habilitado Gorgias como canal real en staging (Marea) con **API Key / Basic auth** (no el OAuth2 Bearer existente, que caduca sin refresh): [#223](https://github.com/Auyan-ai/platform/pull/223) **adapter dual-auth** (Bearer|Basic) + `_is_from_agent` robusto (bool|string) en el webhook + script `configure_staging_integrations --only gorgias` (valida creds contra la API, cifra, registrado **no-primary**). **Migración faltante en staging aplicada a mano:** `add_gorgias_channel` (el enum `channel_type` no tenía `gorgias` → 500). **Dogfood E2E real (email→ticket) cazó 3 bugs, todos con PR+tests:** (1) el enum de arriba; (2) [#224](https://github.com/Auyan-ai/platform/pull/224) **outbound roto** (`source.type:"agent"` → 400 "Not a valid choice"; ahora `send_message` hace GET del ticket y **espeja el último mensaje entrante** — source from↔to, sender↔receiver — patrón que Gorgias exige); (3) [#226](https://github.com/Auyan-ai/platform/pull/226) **email vacío** (Gorgias arma el correo desde `body_html`; mandábamos solo `body_text` → autogeneraba un html solo-cita → correo en blanco; ahora derivamos `body_html` del texto). **Verificado EN VIVO punta a punta:** inbound→agente→outbound→**email con texto**→resolución (cierra el ticket)→reapertura→`order_status` fuera de plazo (#1181, 30-may, ~13 días unfulfilled > plazo de Marea, comparación días-vs-plazo en el AOP order_status)→**escalado** (nota interna con motivo+contexto; SIN asignar porque Marea no tiene `escalation_team_id` — la asignación es config per-cliente). Config en Gorgias = **HTTP Integration** (trigger *ticket-message-created*, body templado con `meta.domain={{ticket.account.domain}}`). **CLAUDE.md:** selección de modelo Fable/Opus/Sonnet con uso+costo (Fable = tier SOBRE Opus, ~2×, NO "Opus rápido"). [#225](https://github.com/Auyan-ai/platform/pull/225) chore: borrado `bloque-0-plan.md` + ref huérfana. **Chip vivo:** persistir `refresh_token` en el OAuth de Gorgias (`oauth_gorgias.py` lo descarta hoy). **Ver "🚀 Arranque sesión 70" abajo.**)_
> _Sesión 68 — **Auditoría 🟠 cerrada + latencia (palancas 2/3) medida en vivo**. Cerrados los 4 hallazgos 🟠 de la auditoría del grafo: [#218](https://github.com/Auyan-ai/platform/pull/218) **re-supervisar tras retry** (`supervisor_retried` dejaba de apagar la supervisión del turno; el anti-loop vive en el nodo supervise) + **`order_id` en el dedup del gate L3** (resuelve visible↔interno vía adapter; ya no se traga una acción L3 sobre OTRO pedido con inputs iguales; fail-safe = acción distinta); [#219](https://github.com/Auyan-ai/platform/pull/219) **guardrails estructurados al supervisor** (`CompiledAOP.guardrails` → state `aop_guardrails`, en vez de parsear el system_prompt con `split("Reglas NO negociables")`) + **RAG degrada a `chunks=[]`** si OpenAI embeddings cae (antes escalaba TODO; la búsqueda en Postgres sí sigue fail-fast). **Latencia palancas 2/3:** [#220](https://github.com/Auyan-ai/platform/pull/220) **router por complejidad** (`_select_reason_model`: Haiku en turnos sin skills/tool_results/pending — solo respond/escalate posible) + **concisión imperativa** (regla global: 1-3 frases por defecto, sin preámbulos de relleno); [#221](https://github.com/Auyan-ai/platform/pull/221) **9º AOP `smalltalk` sin skills** que ACTIVA el router. **MEDIDO EN VIVO (Marea staging):** el router #220 nunca se activaba porque TODOS los AOPs canónicos tienen skills (hasta `default`, 4 L1) → creado `smalltalk` (charla pura, `allowed_skills=[]`); el clasificador enruta "gracias" ahí → **Haiku 1,7s vs Sonnet 3,5s (~50% menos)**, sin supervisor. **Concisión confirmada:** respuesta de devoluciones 267-293 tok vs 476 baseline s67 (~40% menos output). **Hallazgo nuevo:** en turnos con tool+supervisor la latencia la dominan los HOPS secuenciales (devoluciones reales: 3 reason + 2 supervise ≈ 20s por un retry del supervisor), NO el output — palanca futura distinta. `smalltalk` **seedeado solo en Marea** (dogfood); rollout a los demás con `seed_canonical_aops --all` tras mergear #221. #218–#220 MERGEADOS; #221 abierto._
> _Sesión 67 — **Auditoría del grafo + 4 PRs de robustez + latencia medida**. A petición de Kenny, auditoría completa del grafo del agente (11 nodos + routing): 2 bugs 🔴, varios 🟠. Cerrados los 🔴 con TDD: [#213](https://github.com/Auyan-ai/platform/pull/213) **instrumentación latencia/cache** (`trace_label` en `call_claude_with_tools` loguea `dur_ms` + breakdown `in/cache_w/cache_r/out` por llamada — eran los 4 archivos sin commitear de sesión 66); [#214](https://github.com/Auyan-ai/platform/pull/214) **señales residuales en `reason`** (el merge por-key de LangGraph dejaba la tool RECHAZADA por el supervisor en `pending_tool_call` → `route_after_reason` la ejecutaba sin re-supervisión; espejo: un `agent_response` rechazado podía llegar al cliente vía escalate+max_iter — cada retorno de `reason` ahora anula la rama contraria); [#215](https://github.com/Auyan-ai/platform/pull/215) **handle_error → helpdesk** (las escalaciones por error de sistema NO empujaban nota al helpdesk del cliente: faltaba `escalation_created`; además insertaba escalación nueva por cada error → ahora reusa la abierta, patrón de `escalate`); [#216](https://github.com/Auyan-ai/platform/pull/216) **classifier resiliente** — destapado EN VIVO al medir: Haiku devolvió el tool output sin `ambiguity_detected` (required) → `ValidationError` tumbaba el turno entero por `agent_error`. Fix 2 capas: defaults en `_ClassifierOutput` + try/except → degradar a `default`. **Los 4 MERGEADOS, suite 1256 verde.** **Latencia MEDIDA en staging** (send_test_webhook + logs `llm_call`): el **caching pega y persiste entre turnos** (`cache_r=1982` se reusa en el turno siguiente, 46s después, dentro del TTL) — **#211 confirmado**. **Hallazgo clave: la latencia la domina el OUTPUT, no el input** (out=48→2,4s; out=476→7,7s; out=309→6,4s). El caching ya optimizó el input; las palancas reales son concisión, menos tool hops y modelo rápido en turnos simples. Latencia/turno: ~10s con tool (2 llamadas LLM), ~6,4s directo. Supervisor NO corrió (selectivo #191 OK). **Doc nuevo:** [`docs/market-analysis-2026-06.md`](market-analysis-2026-06.md) (rescatado de una rama huérfana `claude/market-analysis-*`): e-commerce vs otros verticales en ES, hallazgo Ley 10/2025 (energía), recomendación = bifurcar discovery en 2 cohortes, NO pivotar. **Ver "🚀 Arranque sesión 68" abajo.**)_
> _Sesión 66 — **Legibilidad del chat + prompt caching del agente**. 2 PRs MERGEADOS: [#210](https://github.com/Auyan-ai/platform/pull/210) **regla global de formato para chat** (texto plano, sin tablas/Markdown que el widget renderiza ilegibles; `aops/compiler.py::_render_global_rules`) verificado E2E; [#211](https://github.com/Auyan-ai/platform/pull/211) **prompt caching del system + tools** en `reason` y `supervise` (`cache_control` ephemeral; `build_system_blocks` separa AOP estable [cacheado] de volátil [fecha/known_facts/RAG]; la fecha ya NO va de preámbulo). Latencia palanca #1 (caching) hecha; medición confirmada en sesión 67._
> _Sesión 65 — **Cierre de deuda + enrutado del escalado al helpdesk**. 4 PRs: [#204](https://github.com/Auyan-ai/platform/pull/204) **retrofit DRY cripto** (load_tenant_context usa el helper `build_commerce_integration_ctx` — fuente única de la cripto de llaves, −199 líneas; cobertura de cripto movida a `tests/test_commerce_context.py`) MERGEADO; [#205](https://github.com/Auyan-ai/platform/pull/205) docs MERGEADO; [#206](https://github.com/Auyan-ai/platform/pull/206) **enrutado del escalado al helpdesk** (nuevo `services/helpdesk_escalation.py`: nota interna con el motivo + asignación al equipo CX; flag `escalation_created` empuja una sola vez, anti-duplicado; best-effort en los 4 webhooks) MERGEADO; [#207](https://github.com/Auyan-ai/platform/pull/207) **nota natural** (dogfood: la nota interna volcaba un JSON con confianza/trace/mensaje duplicado → ahora solo el motivo en lenguaje natural) ABIERTO. **Dogfood en vivo (Chatwoot):** un escalado real publicó la nota interna privada (candado 🔒, no la ve el cliente) con el contexto. **Hallazgo:** el Chatwoot de Marea/Purigu **no tiene Teams** habilitado → la auto-asignación queda diferida; por ahora solo la nota interna (NO setear `escalation_team_id`). **Siguiente:** Markdown en el widget. Ver "🚀 Arranque sesión 66" abajo.)_
> _Sesión 64 — **Chips post-dogfood + resolución autónoma + billing por resolución**. 8 PRs MERGEADOS a develop: [#194](https://github.com/Auyan-ai/platform/pull/194) **país determinista** en update_shipping_address (preserva el del pedido + fallback config, no lo inventa el LLM); [#195](https://github.com/Auyan-ai/platform/pull/195) **H4** plazo de devolución desde la recepción (get_order_status expone fulfilled_at/delivered_at; AOP returns mide desde entrega→envío→created_at); [#196](https://github.com/Auyan-ai/platform/pull/196) **resolución autónoma** (respond marca `resolved`+`resolved_at` vía señal `awaiting_customer_reply` del decide tool; cierra ticket externo tras entregar; reabre si el cliente vuelve; cleanup entrega nudge + cierra abandonadas — migración `resolved_at` **APLICADA en staging**); [#197](https://github.com/Auyan-ai/platform/pull/197) **observabilidad** L3 (approve loguea la ejecución real en `skill_audit_log`); [#198](https://github.com/Auyan-ai/platform/pull/198) **PII** (redacción de dirección/CP en copia forense; operador ve `inputs_raw`); [#199](https://github.com/Auyan-ai/platform/pull/199) **limpieza** (dead code middleware + `reply_model` setting); [#200](https://github.com/Auyan-ai/platform/pull/200) **PRD billing**; [#202](https://github.com/Auyan-ai/platform/pull/202) **order_status fuera de plazo** (no da falsa tranquilidad a un pedido vencido: compara días vs plazo de envío → reconoce el retraso y escala). **Marea re-seedeada** (AOPs canónicos v6 con país/H4/order_status). **Validado E2E en vivo** (widget Chatwoot real): resolución autónoma resolve→reopen→resolve (el ticket de Chatwoot se cierra/reabre solo), país determinista, y order_status escalando un pedido fuera de plazo. **COGS real medido** en una conversación completa: ~$0,077 ≈ **€0,071/resolución** (valida el PRD, incluso por debajo). **Decisión de negocio:** unidad de cobro = **resolución** (cierre sin escalar) con **suelo + overage** → PRD [`docs/billing-resolution-prd.md`](billing-resolution-prd.md) + issue [#201](https://github.com/Auyan-ai/platform/issues/201). **Ver "🚀 Arranque sesión 65" abajo para lo pendiente.**_
> _Sesión 63 — **Dogfood L3 endurecido — 13 PRs (#180–#192)**. Verificación E2E del flujo de cambio de dirección sobre Marea (widget Chatwoot real), analizando conversaciones + traces en Supabase. La primera tanda cerró los 6 hallazgos del análisis inicial: [#180](https://github.com/Auyan-ai/platform/pull/180) fallo L3 honesto (no enmascarar un 404 con "estamos revisando"; queda `pending` para reintento); [#181](https://github.com/Auyan-ai/platform/pull/181) resolver el **número de pedido visible → order_id interno** en las 6 skills de mutación (causa raíz del 404); [#182](https://github.com/Auyan-ai/platform/pull/182) mensaje del gate L3 cálido/contextual; [#183](https://github.com/Auyan-ai/platform/pull/183) no duplicar el gate (idempotencia sobre `pending`); [#184](https://github.com/Auyan-ai/platform/pull/184) **read-back** de la dirección antes de aprobar; [#185](https://github.com/Auyan-ai/platform/pull/185) inferir país (tienda) y provincia (CP), no pedirlos a ciegas. Re-probar destapó 7 más: [#186](https://github.com/Auyan-ai/platform/pull/186) no re-disparar la skill tras aprobar (prompt); [#187](https://github.com/Auyan-ai/platform/pull/187) concisión global (no repetir info ya dada); [#188](https://github.com/Auyan-ai/platform/pull/188) **red determinista** anti-duplicado (reusa approval pending/approved comparando la acción sin `order_id`); [#189](https://github.com/Auyan-ai/platform/pull/189) **memoria de hechos** (inyectar datos ya leídos en reason+supervisor desde `skill_audit_log`, invalidando tras mutación) — corta re-consultas; [#190](https://github.com/Auyan-ai/platform/pull/190) mensaje coherente al reescribir tras una acción ya aplicada (no "sigue en revisión"); [#191](https://github.com/Auyan-ai/platform/pull/191) **supervisor selectivo** (no supervisar respuestas de cortesía sin tools); [#192](https://github.com/Auyan-ai/platform/pull/192) inyectar **acciones L3 completadas** en el contexto para no re-disparar el gate ante un "gracias" — **ABIERTO**, #180–#191 MERGEADOS. **Latencia:** read-back de ~16s → **~5s**. **Decisión:** supervisor en **Sonnet** (Opus solo crítico) por costo. **Re-seeds aplicados a Marea** tras #184/#185/#186; welcome del widget Chatwoot desactivado (evita doble saludo). Pendiente: verificar #192 en vivo, y deuda de **fixtures de eval huérfanas** (slugs legacy ≠ canónicos). Ver "Dogfood E2E Marea" abajo._
> _Sesión 62 — **Dogfood L3 cerrado E2E + 6 fixes**. Cerrado el flujo L3 con approval de punta a punta vía **widget Chatwoot real** (`order_change` → `update_shipping_address` sobre #1181: gate → `pending_approval` → aprobación en dashboard → ejecución real en Shopify → confirmación al cliente → revert a la dirección original). El camino de aprobación estaba **roto de raíz**; el dogfood destapó 5 bugs + 1 de seguridad, todos con PR + tests: [#172](https://github.com/Auyan-ai/platform/pull/172) **H5** colisión `account_id` cross-tenant (índice único parcial + guard fail-closed); [#173](https://github.com/Auyan-ai/platform/pull/173) 500 al aprobar (SkillContext con kwargs obsoletos → helper `build_commerce_integration_ctx`); [#174](https://github.com/Auyan-ai/platform/pull/174) **B1** el dashboard interno no exigía `super_admin` (un `tenant_admin` podía entrar — no era fuga de datos, la API aísla, pero sí frontera de operador rota); [#175](https://github.com/Auyan-ai/platform/pull/175) 500 mensaje `agent_human` sin autor (constraint); [#176](https://github.com/Auyan-ai/platform/pull/176) 422 país en texto libre ("España") → `country_code` ISO; [#177](https://github.com/Auyan-ai/platform/pull/177) mensaje al cliente crudo → redactado con **Haiku** (fallback plantilla); [#178](https://github.com/Auyan-ai/platform/pull/178) **entrega al helpdesk** de los mensajes del flujo L3 (escalate + approve) — **ABIERTO**, resto MERGEADOS. `complaint` también verificado (empatía + escalar, sin L3). **Decisión de producto:** ambos roles aprueban L3, cada uno desde su dashboard (la API ya aísla por tenant). Pendiente: **país determinista** (hoy lo rellena el LLM), H4, H6. Ver "Dogfood E2E Marea" abajo._
> _Sesión 61 — **Fix de raíz Hallazgo 1 (provisioning)**: `provision_tenant` ahora crea `tenant_configurations` + prompt base `system` (helper idempotente `ensure_tenant_config_and_prompt` + script de backfill). [PR #171](https://github.com/Auyan-ai/platform/pull/171) MERGEADO._
> _Sesión 60 — **Fix #5 intent-switch continuity-aware** ([#167](https://github.com/Auyan-ai/platform/pull/167) MERGEADO, cierra 5/5 fixes de grafo) + **dogfood E2E sobre Marea** (Fix #5 multi-turno + order_status #1181 + returns/refunds + **Chatwoot real**) → destapó hallazgos #168 (política KB/facts) y #169 (token Shopify en claro), MERGEADOS._
> _Sesión 59 — **AOPs canónicos + fixes de grafo**. (1) Diseñados y verificados uno a uno los 8 AOPs por defecto de e-commerce ES en [`docs/aop-canonical-design.md`](aop-canonical-design.md). (2) **PR #1 [#163](https://github.com/Auyan-ai/platform/pull/163) MERGEADO**: provisioning copy-on-create — cada tenant nace con sus 8 AOPs + permisos (L1/L2 auto, L3 con approval) vía hook en `provision_tenant`; `aops/canonical.py` es la fuente de verdad + `scripts/seed_canonical_aops.py` para backfill. (3) Fixes de grafo (PR #2): [#164](https://github.com/Auyan-ai/platform/pull/164) (cablear `confidence_threshold` + `require_supervision` por-AOP, antes muertos; guard anti prompt-injection) y [#165](https://github.com/Auyan-ai/platform/pull/165) (fecha/hora TZ-aware del tenant + dep `tzdata`) — **AMBOS ABIERTOS, esperan review/merge**. (4) **Backfill aplicado en staging**: Marea Studio (8 nuevos) y Lunaria (6 nuevos + returns/default actualizados a canónico, `consulta_envio` viejo desactivado) — los 8 canónicos activos + 11 permisos en ambos. PENDIENTE: **Fix #5 intent-switch en sesión nueva** — ver sección abajo)._

## Recaps "hecho en sesión" del arranque s73 + nota latencia


**Hecho en sesión 72 (autónoma, 3 PRs MERGEADOS, suite 1306 verde):** ~~Zendesk E2E (código)~~ ✅ [#232] dual-auth API token/Basic (espejo de Gorgias) + provider `zendesk` en configure (el enum ya tenía zendesk → sin migración; outbound shape estándar) — falta E2E en vivo (punto 2); ~~Latencia HOPS (prompt)~~ ✅ [#233] el AOP returns secuencia "verificar antes de afirmar" → mata el reject+retry — falta re-seed Marea + curar facts + medir (punto 3); ~~Billing Bloque 2 (motor)~~ ✅ [#234] resolution_events + conteo con ventana §2.3 + tiers + endpoint + hooks — Stripe + aplicar migración + crear suscripciones = manual (punto 4). Rollout `smalltalk` descartado (simuladores). **Post-merge:** las 2 migraciones nuevas aplicadas a staging y el flujo completo verificado EN VIVO sobre Marea (turno de devoluciones: `respond` sin error → política real → `resolution_event` creado).
**Hecho en sesión 71:** ~~Re-auditoría de robustez del grafo~~ ✅ + ~~hallazgo 🔴 L3-sin-approval cerrado~~ ✅ (PR1 piso `_l3_requires_human_approval` + migración `l3_autonomy_acknowledged_at/_by` NULL=fail-safe + propagación al state; PR2 endpoint 422 sin `acknowledge_l3_autonomy` + `upsert` sella/limpia). 1297 verde. **Falta:** correr la migración en staging + PR a develop. Backlog auditoría #2/#3 abierto (ver punto 0).
**Hecho en sesión 70:** ~~Latencia palanca HOPS~~ ✅ 3 palancas, 2 PRs validados en vivo: [#228] P1 (cache del retry: `reason#3` ahora `cache_r=2986`, antes 0) + P2 (criterio del supervisor); [#229] P3 (no supervisar lecturas L1: turno de devoluciones 7→6 hops, confirmado con traces antes/después). Hallazgo de método: la palanca real (P3) se vio en el trace, no era P2.
**Hecho en sesión 69:** ~~Verificar Gorgias E2E~~ ✅ punta a punta (Basic auth [#223]; 3 bugs cazados: enum `channel` + [#224] outbound `source.type`/mirror + [#226] `body_html` email vacío; resolución+reapertura+escalado por plazo verificados en vivo); ~~CLAUDE.md modelos Fable/Opus/Sonnet~~ ✅; [#225] docs.
**Hecho en sesión 68:** ~~4 hallazgos 🟠 de la auditoría~~ ✅ [#218]/[#219]; ~~latencia palanca concisión (a)~~ ✅ [#220] (267-293 tok vs 476); ~~router Haiku (c)~~ ✅ [#220]+[#221] (1,7s vs 3,5s en charla, vía AOP `smalltalk`); ~~medir todo en vivo~~ ✅.
**Hecho en sesión 67:** ~~Auditoría del grafo~~ ✅; ~~instrumentación latencia/cache~~ ✅ [#213]; ~~señales residuales~~ ✅ [#214]; ~~handle_error → helpdesk~~ ✅ [#215]; ~~classifier resiliente~~ ✅ [#216].
**Hecho en sesión 66:** ~~Formato Markdown chat~~ ✅ [#210]; ~~prompt caching (palanca #1)~~ ✅ [#211].

**Nota latencia (b, descartado en s68):** "menos tool hops vía KB/facts" NO se atacó como código del grafo — es curación de AOPs/facts per-tenant; queda dentro de la palanca de HOPS (punto 3) y del dogfood.


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

## Bloque 0.11 — Agent Verification Staging (narrativa histórica) + tabla staging al 2026-06

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

