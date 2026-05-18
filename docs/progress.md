# Auyan — Estado del proyecto

_Última actualización: 2026-05-18 (sesión 20 — Sprint 9.1 idempotency + Sprint 9.2 Skills L2 + permission gate)_

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

## Sprint 2 — Refactor services/routers a asyncpg (en curso)

**Objetivo:** dejar listos los endpoints administrativos (tenants, conversations, escalations) sobre el paradigma asyncpg + `tenant_scope`, con auth Supabase JWT real, para poder arrancar el dashboard interno.

**Branch:** `feat/sprint2-services-asyncpg` (local, sin push aún)

### Diagnóstico inicial (clave para retomar)

El progress.md anterior decía "refactor de services + routers a asyncpg" — pero al inspeccionar el código se descubrió que el **core del flujo inbound ya está reescrito en asyncpg** (vive en `routers/webhooks.py`). Lo que realmente se eliminó y no se reemplazó son:

- `core/security.py` — auth Bearer JWT (no había reemplazo en absoluto)
- `routers/tenants.py` — endpoint admin para tenants
- `services/tenants.py`, `services/escalation.py` — escalación manual desde humanos
- Endpoints admin para conversations y escalations (nunca existieron)

Por eso este refactor en realidad **agrega los endpoints administrativos faltantes** + **auth real**, manteniendo el patrón asyncpg ya validado.

### Patrón acordado

```
routers/   → HTTP + validación + scope de transacción (Depends auth + tenant_scope)
services/  → reglas de negocio multi-paso, reciben `conn: asyncpg.Connection`
db/queries → SQL puro, función + conn + params, devuelve modelos Pydantic
core/      → security (JWT), errors (excepciones de dominio + handlers)
```

Reglas:
- **El router decide el scope de la transacción**, no el service. Así combinar 2 services en una request mantiene atomicidad.
- **Services no importan FastAPI.** Lanzan excepciones de dominio (`NotFoundError`, `ForbiddenError`); un exception handler global las traduce a HTTP.
- **Auth via Supabase JWT** (HS256), `AuthContext` con `user_id`/`tenant_id`/`role`/`email`. `tenant_admin`/`tenant_agent` operan sobre su tenant; `super_admin` requiere header `X-Tenant-Id`.
- **Cache de usuarios**: `TTLCache(maxsize=1000, ttl=60s)` configurable. Maxsize acotado.

### Avances sesión 4 (5 commits)

| Commit | Qué hace |
|---|---|
| `feat(api): excepciones de dominio + handler global` | `core/errors.py` con `DomainError` + subclases (`NotFoundError`, `ForbiddenError`, `UnauthorizedError`, `ConflictError`, `ValidationFailed`). Handler global mapea a `{"error": code, "detail": msg}`. |
| `chore(api): agregar poetry.lock` | Cierra deuda del Sprint 1. Builds Railway ahora reproducibles. |
| `style(tests): partir línea larga en test_defaults` | Lint fix preparatorio. |
| `chore(api): agregar pyjwt + cachetools` | `pyjwt` para HS256 (preferido sobre python-jose por seguridad); `cachetools` para TTLCache acotado; `types-cachetools` en dev. |
| `feat(api): auth Supabase JWT con AuthContext + dependencies` | `core/security.py` completo: `AuthContext`, `get_auth_context`, `get_tenant_id`, `require_role`, cache TTL. `db/queries.get_user_for_auth`. Settings JWT en config. Sección de auth en `.env.example`. |

**Tests sesión 4:** 30 nuevos (9 errors + 21 security). Suite total 157 verde. Ruff limpio.

### Avances sesión 5 (1 commit — [00b6612](https://github.com/Auyan-ai/platform/commit/00b6612))

| Área | Qué se hizo |
|---|---|
| `db/models.py` | `created_at` agregado a `Conversation` y `Escalation` |
| `db/queries.py` | 6 queries nuevas: `list_conversations`, `get_messages_for_conversation`, `get_escalation`, `list_escalations`, `claim_escalation` (CAS), `resolve_escalation` (CAS) |
| `services/tenants.py` | `get_tenant`, `get_tenant_config` con `NotFoundError` |
| `services/conversations.py` | `list_tenant_conversations`, `get_conversation_detail`, `reply_to_conversation`, `escalate_conversation`, `close_conversation` |
| `services/escalations.py` | `list_tenant_escalations`, `claim_tenant_escalation`, `resolve_tenant_escalation` |
| `routers/tenants.py` | `GET /tenants/me`, `GET /tenants/me/config` |
| `routers/conversations.py` | `GET /conversations`, `GET /conversations/{id}`, `POST /{id}/reply`, `POST /{id}/escalate`, `POST /{id}/close` |
| `routers/escalations.py` | `GET /escalations`, `POST /{id}/claim`, `POST /{id}/resolve` |
| `main.py` | Wire up de los 3 routers nuevos |

**Tests sesión 5:** 25 nuevos (5 tenants + 13 conversations + 7 escalations). Suite total **182 verde**. Ruff limpio.

### Avances sesión 6 — smoke test + fix ES256

| PR | Qué hace |
|---|---|
| [PR #12](https://github.com/Auyan-ai/platform/pull/12) | `.claude/` agregado a `.gitignore` |
| [PR #13](https://github.com/Auyan-ai/platform/pull/13) | `supabase/seed.sql`: columnas `confirmation_token`, `recovery_token`, `email_change_token_new`, `email_change` con `''` (no NULL) + insert en `auth.identities`. Fix al crash de GoTrue al arrancar. |
| [PR #14](https://github.com/Auyan-ai/platform/pull/14) | `feat/sprint2-services-asyncpg` → `develop`. Sprint 2 completo mergeado a staging. |
| [PR #15](https://github.com/Auyan-ai/platform/pull/15) | `fix(auth): ES256 JWKS support`. Supabase usa ES256 (ECDSA) en proyectos nuevos. `security.py` reescrito para verificar JWT con clave pública del JWKS (`/auth/v1/.well-known/jwks.json`). Cache 1 h + re-fetch en rotación. `config.py`: `supabase_jwt_secret` opcional, default algorithm ES256. |
| [PR #16](https://github.com/Auyan-ai/platform/pull/16) | `cryptography>=44.0` + `pyjwt[crypto]` en `poetry.lock`. Sin esto, `ECAlgorithm` no está disponible en runtime. |

**Validado end-to-end en staging:**
- `GET /tenants/me` con JWT de `agente@lunaria.test` → 200 con datos completos de Lunaria (id, slug, name, status)
- `GET /tenants/me/config` con JWT → 200 con `agent_model`, `escalation_threshold`, `active_channels`, `branding`
- `GET /tenants/me` sin token → 401 `missing_bearer_token`

**Issue resuelto sobre Railway auto-deploy:** el GitHub App de Railway dejó de disparar builds tras PR #14. Los botones "Redeploy" y las mutations `serviceInstanceDeploy*` fallan con "Problem processing request". El workaround que funciona es la mutation `environmentTriggersDeploy` por GraphQL con HTTP/1.1 — guardado en memoria para sesiones futuras. Reportable a soporte de Railway si vuelve a pasar.

### Pendiente del Sprint 2

- [ ] **`docs/architecture-services.md`** — 1 página con el patrón de capas
- [x] **PR contra develop** — mergeado (PR #14)

### Empezar aquí en la próxima sesión — usar **Sonnet**

1. Arrancar Sprint 3: dashboard interno `apps/web` con Next.js + Supabase Auth
2. Opcional: escribir `docs/architecture-services.md` (1 página, patrón de 4 capas)

---

## Sprint 3 — Dashboard interno (completado ✅)

**Objetivo:** Dashboard `apps/web` que consuma los 10 endpoints admin del API como super_admin. Solo `(dashboard)` en este sprint; `/clients/` es Sprint 4.

**URLs de staging:**
- API: `https://platform-staging-fdb7.up.railway.app`
- Web: `https://auyan-web-staging.up.railway.app`

**Diseño de arquitectura:** [docs/architecture-web.md](architecture-web.md) — aprobado al inicio del sprint.

### Sub-PR 3.1 — completado (commit b1bb9c5)

| Área | Qué se hizo |
|---|---|
| Monorepo Node | pnpm 11.1.2 + workspaces, `biome.json` raíz, `package.json` con scripts `gen:api-types` y `build:web` |
| `packages/shared` | `enums.ts` con los Literal types espejando `db/models.py`, `index.ts` re-exporta |
| `apps/web` base | Next.js 15 App Router, TypeScript strict, Tailwind v4, shadcn configurado (`components.json`), Biome |
| Auth | `@supabase/ssr`: `lib/supabase/client.ts` (browser) + `lib/supabase/server.ts` (RSC), middleware de sesión con redirect |
| Login | `/login` funcional — `signInWithPassword` + redirect a `/dashboard` post-login |
| Dashboard shell | Layout protegido en RSC que valida sesión antes de renderizar |
| `.gitignore` | Reglas Next.js + pnpm + corrección de `lib/` anclada a raíz (no pisaba `apps/web/lib/`) |

### Sub-PR 3.2 — completado (commit 0596f07)

| Área | Qué se hizo |
|---|---|
| `packages/shared` | `api-types.ts` generado desde staging `/openapi.json`; export path `@auyan/shared/api-types` |
| `apps/web/next.config.ts` | `transpilePackages: ['@auyan/shared']` — Next.js compila TS del workspace sin build |
| `lib/api/client.ts` | Factory `apiClient(token, tenantId?)` con `openapi-fetch` + tipos generados |
| `lib/api/query-keys.ts` | Fábrica de query keys normalizada para TanStack Query |
| `lib/api/hooks/tenants.ts` | `useMyTenant()`, `useMyTenantConfig()` client-side |
| `components/providers.tsx` | `QueryClientProvider` con staleTime 1 min |
| `app/layout.tsx` | Envuelve árbol en `<Providers>` |
| `app/(dashboard)/page.tsx` | Smoke test RSC — `GET /tenants/me` con manejo explícito de 403 para super_admin |

### Sub-PR 3.3 — completado ([PR #19](https://github.com/Auyan-ai/platform/pull/19))

| Área | Qué se hizo |
|---|---|
| `components/inbox/ConversationList.tsx` | Inbox con filtros de status (6 tabs), polling 5 s, paginación prev/next |
| `lib/api/hooks/conversations.ts` | `useConversations()` con TanStack Query, staleTime 0, refetchInterval 5 s |
| `app/(dashboard)/tenants/[tenantId]/conversations/page.tsx` | Página de lista por tenant |
| `apps/api/main.py` | `CORSMiddleware` — fix crítico para peticiones cross-origin del browser |
| `apps/api/core/config.py` | `allowed_origins` con default `localhost:3000,localhost:3001` |

**Tenant correcto para Lunaria:** `11111111-1111-1111-1111-111111111111` (no el 33333333... de pruebas iniciales).

### Sub-PR 3.4 — completado ([PR #20](https://github.com/Auyan-ai/platform/pull/20))

| Área | Qué se hizo |
|---|---|
| `components/inbox/ConversationDetail.tsx` | Hilo de mensajes con burbujas por rol, scroll al último, polling 5 s |
| Composer | Responder (Cmd+Enter), Escalar (razón inline), Cerrar — sólo lectura si closed/resolved |
| Hooks | `useConversation`, `useReplyMutation`, `useEscalateMutation`, `useCloseMutation` |
| Layout | `conversations/[id]/layout.tsx` — chat a pantalla completa (-m-8) |

### Sub-PR 3.5 — completado ([PR #21](https://github.com/Auyan-ai/platform/pull/21))

| Área | Qué se hizo |
|---|---|
| `components/inbox/EscalationQueue.tsx` | Cola con filtros, botones Tomar/Resolver por fila, link a conversación |
| Hooks | `useEscalations`, `useClaimMutation`, `useResolveMutation` |
| Nav sidebar | Links a Conversaciones y Escalaciones (hardcodeado a Lunaria, reemplazado en 3.6) |

### Sub-PR 3.6 — completado ([PR #22](https://github.com/Auyan-ai/platform/pull/22))

| Área | Qué se hizo |
|---|---|
| `GET /tenants/admin/list` | Endpoint `super_admin` only, sin tenant_scope, lista todos los tenants activos |
| `db/queries.list_all_tenants` | Query sin tenant_scope para super_admin |
| `components/nav/TenantSwitcher.tsx` | Dropdown de tenants con dot de status, navega manteniendo sección activa |
| `components/nav/Sidebar.tsx` | Sidebar dinámico: extrae tenantId de la URL, resalta item activo |

**Conversaciones de prueba creadas** para Lunaria via webhook inbound (agente escaló por cuota OpenAI).

### Sub-PR 3.7 — completado ([PR #24](https://github.com/Auyan-ai/platform/pull/24) + fixes #26–#29)

| Área | Qué se hizo |
|---|---|
| `apps/web/Dockerfile` | Build multistage pnpm workspace desde raíz, Next.js standalone, runner mínimo |
| `next.config.ts` | `output: standalone` + `outputFileTracingRoot` para monorepo |
| `api-types.ts` | Regenerado — incluye `GET /tenants/admin/list` tipado |
| `useAdminTenants` | Migrado de fetch manual a openapi-fetch tipado |
| Railway | Servicio `auyan-web` creado, dominio `https://auyan-web-staging.up.railway.app` |
| `ALLOWED_ORIGINS` | Seteado en Railway para el servicio API: `localhost:3001,auyan-web-staging.up.railway.app` |

**Fixes de deploy resueltos:**
- [PR #26](https://github.com/Auyan-ai/platform/pull/26) — eliminado `railway.toml` raíz (conflicto: aplicaba a todos los servicios, web arrancaba con imagen Python)
- [PR #27](https://github.com/Auyan-ai/platform/pull/27) — eliminado `--mount=type=cache` no soportado en Railway
- [PR #28](https://github.com/Auyan-ai/platform/pull/28) — cambiado `node:20-slim` → `node:22-slim` (pnpm 11 requiere Node ≥ 22)
- [PR #29](https://github.com/Auyan-ai/platform/pull/29) — eliminado `COPY public` inexistente

**Configuración manual en Railway dashboard (no en código):**
- `auyan-web`: `PORT=3000` como variable de entorno (Railway inyecta 8080 por defecto)
- `platform` (API): healthcheck path `/health` y restart policy seteados vía dashboard (ya no viene de railway.toml)

---

## Sprint 4 — Dashboard cliente por tenant ([PR #31](https://github.com/Auyan-ai/platform/pull/31))

**Objetivo:** Vista read-only para `tenant_admin` — el cliente observa su soporte sin tener herramientas de agente.

**Estado:** PR listo para merge. Pendiente validación en staging con usuario `tenant_admin` real.

### Sub-PR 4.1 — API (commit e7b23bd)

| Área | Qué se hizo |
|---|---|
| `routers/users.py` | `GET /users/me` → `{ user_id, tenant_id, role, email }` — accesible a cualquier rol |
| `routers/tenants.py` | `GET /tenants/me/metrics` → `{ total, by_status, resolution_rate, escalation_rate }` — solo `tenant_admin` y `super_admin` |
| `db/queries.py` | `get_tenant_metrics` con COUNT FILTER por status en una sola query |
| `services/tenants.py` | `get_tenant_metrics` calcula rates en Python |
| Tests | 7 nuevos — suite total **189 verde** |

### Sub-PR 4.2 — Auth routing + layout cliente (commit 5e2867a)

| Área | Qué se hizo |
|---|---|
| `lib/api/users.ts` | `fetchCurrentUser(token)` — helper sin tipos generados, usable en SSR y CSR |
| `login/page.tsx` | Post-login llama `/users/me`; `tenant_admin` → `/clients/{id}/overview`, otros → `/dashboard` |
| `app/(clients)/layout.tsx` | RSC: verifica sesión + rol `tenant_admin`, obtiene nombre del tenant, renderiza `ClientSidebar` |
| `components/clients/ClientSidebar.tsx` | Sidebar con tenant name, nav a Overview / Conversaciones / Escalaciones |

### Sub-PR 4.3 — Overview con métricas (commit f51cf72)

| Área | Qué se hizo |
|---|---|
| `lib/api/hooks/metrics.ts` | `useMetrics(tenantId)` → `GET /tenants/me/metrics`, stale 30s / refetch 60s |
| `components/clients/MetricsCards.tsx` | 4 cards (total, activas, escaladas, resueltas) + 2 stat badges (tasas) con skeleton |
| `components/clients/RecentConversations.tsx` | Tabla últimas 10 conversaciones con links al detalle cliente |
| `app/(clients)/[tenantId]/overview/page.tsx` | RSC que compone las dos secciones |

### Sub-PR 4.4 — Vistas read-only (commit ec0a993)

| Área | Qué se hizo |
|---|---|
| `ConversationList.tsx` | Prop `basePath?` para controlar destino de links |
| `ConversationDetail.tsx` | Props `readOnly?` + `backHref?` — oculta Composer si `readOnly=true` |
| `EscalationQueue.tsx` | Props `readOnly?` + `conversationBasePath?` — oculta botones claim/resolve |
| Páginas `/clients/[tenantId]/...` | conversations, conversations/[id], escalations — todas reutilizan componentes internos |

### Tipos regenerados (commit 4c5a659)

`api-types.ts` regenerado — incluye `CurrentUserResponse`, `TenantMetricsResponse`, `ConversationStatusCounts`. Hook `useMetrics` migrado a `apiClient` tipado.

### Deuda registrada en Sprint 4

- **Tiempo promedio de respuesta**: requiere cálculo de timestamps de mensajes en API — postergado por bajo volumen de datos.

### Estado final del Sprint 4

- PR #31 mergeado ✅
- Flujo `tenant_admin` validado en staging ✅ (PRs #37–#39 cerraron bugs de redirect y logout)
- Créditos OpenAI y Anthropic cargados ✅ — agente responde en modo real
- `WEBHOOK_SECRET` local sincronizado con Railway ✅

### Empezar aquí en la próxima sesión — usar **Sonnet**

1. **UI polish** — dashboard funcional pero sin diseño fino, refinar con shadcn/ui
2. **Integraciones** — cablear Chatwoot, Zendesk, Shopify al flujo del agente

---

## Deuda técnica registrada para Sprint 2+

- **Script de upload de vars a Railway debe stripear comentarios inline** — el script actual toma todo lo que hay después del `=`, incluyendo `# comentarios`. Reescribirlo para parsear `.env` igual que bash.
- ~~**Refactor de services + routers al paradigma asyncpg**~~ → reinterpretado como "agregar endpoints admin faltantes + auth real". En curso (Sprint 2).
- ~~**`poetry.lock` ausente**~~ → resuelto en sesión 4 ([commit 6d1023f](https://github.com/Auyan-ai/platform/commit/6d1023f)).
- **Rol `auyan_backend` en Supabase con `NOBYPASSRLS`** — actualmente conectamos con `postgres` (bypass RLS). La defensa multi-tenant depende solo de `WHERE tenant_id = $1` y el GUC por request.
- **Tests de integración contra Postgres+pgvector real** — hoy todo es unit con mocks.
- **Integraciones de canales** (`chatwoot.py`, `zendesk.py`, `shopify.py`) son clientes HTTP esqueleto — cablear con el flujo del agente.
- ~~**CI ausente**~~ → resuelto en sesión 9 ([PR #41](https://github.com/Auyan-ai/platform/pull/41)). GitHub Actions con ruff + pytest + tsc en cada PR.
- ~~**`.claude/` no está en `.gitignore`**~~ → resuelto en sesión 6 ([PR #12](https://github.com/Auyan-ai/platform/pull/12)).
- **Errores mypy preexistentes** en `db/models.py`, `db/queries.py`, `db/client.py`, `core/config.py` (14 errors `[type-arg]` y `[no-any-return]`). No bloquean la suite pero ensucian el typecheck.
- **`search_products` usa `?title=` (coincidencia exacta)** — la Admin REST API de Shopify no hace substring search. Migrar a Admin GraphQL API (`products(first: N, query: $q)`) para búsqueda full-text real.
- **Razonamiento del agente visible en el dashboard** — mostrar en el hilo de conversación (dashboard interno y cliente) qué skills llamó el agente, input/output de cada una, y confianza de la decisión final. Da transparencia a operadores y tenants. Opciones: (A) mensaje `role="agent_trace"` en Supabase sin migración, (B) leer trace de Langfuse via API, (C) campo `agent_trace` jsonb en `messages`. Evaluar A primero.

**Context engineering — gaps identificados (sesión 19, 2026-05-18):**
- **Memory cross-conversación** (alta prioridad) — solo cargamos historial de la conversación actual. Un cliente recurrente no tiene contexto de su historial previo. Fix: cargar últimas N conversaciones resueltas del mismo `end_customer_id` al arrancar el grafo.
- **Glossary block** (alta prioridad) — no hay bloque dedicado para terminología de la marca. Fix: campo `glossary` en YAML frontmatter del AOP + `_render_glossary()` en compiler.
- **Condiciones por observación mid-turno** (media prioridad) — el AOP se clasifica una vez; si el cliente cambia de tema mid-turno, no hay re-inyección de contexto. Fix: detección de señales críticas en el nodo `reason`.
- **Brand voice por AOP** (media prioridad) — voice está en `tenant_config` global, no overrideable por AOP. Fix: `voice_override` en frontmatter.
- **Detección de alucinaciones automática** — actualmente solo detección manual en Langfuse. Plan: LLM-as-judge en Slow Agent (Sprint 11). Mientras tanto, usar KB con datos fantasiosos específicos (script `seed_kb.py`).
- **Webhook idempotency** (bloqueador de producción) — reintentos del cliente pueden duplicar mensajes/escalaciones. Agregar `idempotency_key` deduplication.
- **Rate limiting + cost controls** (bloqueador de producción) — no hay límites por tenant ni presupuesto de tokens. Riesgo de DDoS y bills explosivos.
- Ver análisis completo en `docs/architecture-agent-v2.md` sección 19.

---

## Sprint 5 — Mejoras al grafo (completado ✅)

Bugs encontrados y corregidos en sesión de pruebas end-to-end (2026-05-16) → [PR #40](https://github.com/Auyan-ai/platform/pull/40):

- **`escalate.py` persiste el mensaje del agente** — el nodo ahora llama `insert_message(role="agent_ai", direction="outbound")` igual que `respond.py`. El mensaje de handoff aparece en el hilo del dashboard.

- **Sin escalaciones duplicadas** — nueva query `get_open_escalation_for_conversation` que detecta escalaciones activas (`pending`/`claimed`). Si ya existe una, el nodo la reutiliza sin crear duplicados.

- Suite: **193/193** verde. Validado en staging con flujo de dos mensajes consecutivos.

---

## Sesión 10 — Diseño arquitectural agente v2 (2026-05-17)

**Sin commits ni código** — sesión de diseño puro. Resultado: [`docs/architecture-agent-v2.md`](architecture-agent-v2.md) (~1500 líneas, 18 secciones).

### Lo que se decidió

Cuatro cambios estructurales sobre el agente actual, inspirados en Sierra (Constellation, Skills) y Decagon (AOPs, Duet):

1. **Skills framework** — cada acción del agente es clase tipada con I/O Pydantic, registrada en registry, con tier L1/L2/L3.
2. **AOPs (Agent Operating Procedures)** — comportamiento del agente en YAML frontmatter + markdown body, editable runtime desde dashboard. Tools scopeadas por AOP.
3. **Supervisor pattern** — Sonnet supervisa tools L1/L2, Opus supervisa L3 (acciones financieras).
4. **Slow agent** — job LLM-as-judge que propone diffs a los AOPs (con sampling + Sonnet first para controlar costo).

### Decisiones lockeadas
- **AOP storage:** DB con versionado append-only + workspaces (prod/staging). Editor en dashboard interno.
- **MCP:** Sprint 14+. Primero validar con skills nativos Python.
- **Supervisor:** Sonnet para L1/L2, Opus para L3, con `reject_kind: tactical | structural` para distinguir reintento vs escalación.
- **Eval harness:** obligatorio Sprint 7, no opcional. Mínimo 13 fixtures/AOP. Gate de promotion `staging → production`.
- **PII policy:** pseudonimización con salt por tenant, retención 90d hot / 180d hash. GDPR-ready.
- **Conversation lifecycle:** estado `closed_abandoned`, timeouts por canal en `tenant_config`, job cada 15min.

### Correcciones post-revisión del user
- **Math honesta:** removido "90%×90%=99%" (falso por correlación de errores). Apuntamos a 40-60% reducción de errores write, a medir.
- **Tono fuera del AOP** — vive en `tenant_config.agent_voice`. AOPs solo describen QUÉ hacer.
- **Multi-intent:** clasificador devuelve top-2 + `ambiguity_detected`. Persistencia del AOP entre turnos con `lock_for_turns`.
- **Cache invalidation multi-worker:** plan Sprint 9 con Redis pub/sub o Postgres NOTIFY.
- **Slow agent realista:** sampling (escaladas + L2/L3 + 10% sample), Sonnet first, semanal manual antes de nightly.

### Plan multi-sprint (lockeado en sección 16 del doc)

| Sprint | Foco |
|---|---|
| **6** | Skills framework + Shopify read tools L1 + ReAct loop + lifecycle básico |
| **7** | AOPs en DB + selector de intent + workspaces + UI editor + **eval harness obligatorio** |
| **8** | Supervisor pattern (Sonnet/Opus por tier) con tactical/structural |
| **9** | Skills L2 + permissions + audit log con PII + idempotency + cache invalidation |
| **10** | Skills L3 + human approval mode |
| **11** | Slow agent skeleton (sampling + Sonnet judge) |
| **12** | Unified KB + Zendesk bidireccional + reapertura |
| **13** | Versionado activo + A/B testing |
| **14+** | MCP server |

### Backlog futuro (no asignado a sprint)
- Modo proactivo / concierge (carritos abandonados, upsell, recuperación pasivos)
- WhatsApp (Twilio o 360dialog)
- Instagram (Meta API)
- Postmark email canal completo
- Embedding router pre-filtro al `select_aop`
- Chat widget embebible (`apps/widget`)
- Onboarding flow para nuevos tenants

---

## Sprint 6 — Skills framework + Shopify L1 + ReAct loop

### Sub-PR 6.1 — Skills framework (en curso, sesión 11)

| Área | Qué se hizo |
|---|---|
| `apps/api/skills/__init__.py` | Módulo creado |
| `apps/api/skills/base.py` | `SkillTier`, `SkillInput`, `SkillOutput`, `SkillContext` (frozen dataclass), `Skill` ABC con `slug/description/tier/input_schema/output_schema/requires_idempotency/default_threshold` como ClassVar + `to_anthropic_tool()` + `TIER_THRESHOLDS` |
| `apps/api/skills/registry.py` | `SkillRegistry` singleton de clase: `register()` (decorator-compatible), `get()`, `list_for_aop()`, `_reset()` para tests |
| `apps/api/tests/skills/test_base.py` | 25 tests: instanciación, validación I/O, `SkillContext` inmutable, `to_anthropic_tool()` shape/schema/required, `execute()` async |
| `apps/api/tests/skills/test_registry.py` | 14 tests: registro, lookup, decorador, overwrite, unknown slug, list_for_aop orden/vacío/error |

**Suite total:** 232/232 verde. Ruff limpio.

### Sub-PR 6.2 — Shopify L1 skills + cliente ([PR #44](https://github.com/Auyan-ai/platform/pull/44))

| Área | Qué se hizo |
|---|---|
| `skills/base.py` | `SkillContext` extendido con `shopify_domain` y `shopify_token` opcionales (backward compatible) |
| `integrations/shopify.py` | Reescrito: `get_order`, `get_order_by_name`, `get_orders_by_email`, `search_products`, `get_customer_by_email`, `get_orders_by_customer_id`, `get_policies`, `cancel_order` (L3 placeholder) |
| `skills/shopify/_models.py` | Modelos compartidos: `OrderSummary`, `FulfillmentInfo`, `ProductSummary`, `ProductVariant`, `CustomerInfo`, `PolicyInfo` + helpers `first_tracking_url`, `strip_html`, `map_order_summary`, `map_product_summary` |
| 5 skills L1 | `shopify.get_order_by_email`, `shopify.get_order_status`, `shopify.get_product_info`, `shopify.get_customer_history`, `shopify.get_shop_policies` — todas con `@SkillRegistry.register` |
| Tests | 39 nuevos (17 cliente httpx mockeado + 22 skills ShopifyClient mockeado) |

**Suite total:** 270/270 verde.

### Sub-PR 6.3a — execute_skill node + state ([PR #46](https://github.com/Auyan-ai/platform/pull/46))

| Área | Qué se hizo |
|---|---|
| `agents/state.py` | Campos del loop ReAct: `pending_tool_call`, `tool_results`, `tool_iterations`, `max_tool_iterations`, `allowed_skills` |
| `agents/nodes/execute_skill.py` | Resuelve slug en registry, valida input contra schema Pydantic, ejecuta. Errores operacionales (no permitida, slug inexistente, input inválido, skill que lanza) → `tool_result` con `is_error=True`. `build_skill_context` lee creds Shopify de `tenant_config.extra`. |
| Tests | 21 tests con cobertura completa |

**Sin tocar `reason` ni el grafo** — preparación para 6.3b.

### Sub-PR 6.3b — loop ReAct cableado al grafo ([PR #47](https://github.com/Auyan-ai/platform/pull/47))

| Área | Qué se hizo |
|---|---|
| `integrations/anthropic_client.py` | `call_claude_with_tools` (plural) acepta lista de tools + `tool_choice` configurable |
| `agents/nodes/reason.py` | Reescrito: construye `tools = [decide, *skill_tools]` desde `allowed_skills`, `tool_choice={"type":"any"}`. Si LLM elige skill → `pending_tool_call`. Reconstruye mensajes multi-turn con bloques `tool_use`/`tool_result` de iteraciones previas. Acumula tokens. |
| `agents/graph.py` | Nodo `execute_skill` cableado. `route_after_execute_skill` → `reason` o `escalate` si max_iter. Edges del loop ReAct. |
| `agents/service.py` | State inicial con defaults del loop |
| `agents/nodes/load_tenant_context.py` | Lee `tenant_config.extra.allowed_skills` y `max_tool_iterations` para opt-in per tenant antes de Sprint 7 |
| `agents/nodes/execute_skill.py` | Setea `escalation_reason` cuando se hit max_iter |
| Tests | 8 adaptados + 7 nuevos en `test_reason_node.py` + tests del routing + 2 E2E del loop ReAct |

**Suite total:** 311/311 verde. Ruff limpio.

### Activación per tenant (Sprint 6.4+)

Sin AOPs aún (Sprint 7), los tenants pueden opt-in agregando a `tenant_configurations.extra`:
```json
{
  "allowed_skills": ["shopify.get_order_by_email", "shopify.get_order_status"],
  "max_tool_iterations": 5,
  "shopify_domain": "mishop.myshopify.com",
  "shopify_token": "shpat_..."
}
```

### Sub-PR 6.3c — fix crítico: bootstrap del SkillRegistry ([PR #49](https://github.com/Auyan-ai/platform/pull/49))

Bug encontrado durante pruebas e2e: el `SkillRegistry` quedaba vacío al arrancar el API en producción porque nadie importaba los módulos de skills. El decorador `@SkillRegistry.register` se ejecuta al importarse el módulo, pero `main.py` no los importaba.

| Archivo | Cambio |
|---|---|
| `apps/api/skills/__init__.py` | Side-effect import del subpaquete `shopify` |
| `apps/api/skills/shopify/__init__.py` | Side-effect imports de los 5 módulos L1 |
| `apps/api/main.py` | `import apps.api.skills` al cargar el módulo |
| `apps/api/tests/skills/test_bootstrap.py` | 6 tests nuevos (5 paramétricos via subprocess + 1 estático) |

**Suite total:** 317/317 verde.

### Validación end-to-end en staging (sesión 12 — 2026-05-17)

Tienda Shopify de prueba: `lunaria-eleq1sc5.myshopify.com` (activada via `scripts/activate_shopify.py`).
Scripts creados: `apps/api/scripts/activate_shopify.py` y `apps/api/scripts/send_test_webhook.py`.

| Prueba | Skill llamada | Resultado |
|---|---|---|
| "¿Cuál es la política de devoluciones?" | `shopify.get_shop_policies` | Respuesta con datos reales: 30 días, condición original ✅ |
| "¿Dónde está mi pedido?" (sin email) | ninguna | Agente pidió email/número — comportamiento correcto ✅ |
| "Mi email es auyan.cx@gmail.com, ¿mis pedidos?" | `shopify.get_order_by_email` | Consultó Shopify, 0 pedidos → respuesta apropiada ✅ |
| "¿Tienen vestidos de noche?" | `shopify.get_product_info` | Buscó catálogo → detectó que es tienda de joyería ✅ |

Trace IDs de referencia:
- `b24de5bd` — políticas
- `eaeb97fc` — pedido por email
- `9179a2c4` — producto

**Sprint 6 completado ✅** — Skills framework + Shopify L1 + loop ReAct validado e2e en staging.

### Sub-PR 6.4 — Lifecycle de conversación ([PR #51](https://github.com/Auyan-ai/platform/pull/51))

| Área | Qué se hizo |
|---|---|
| `supabase/migrations/20260517000000_add_closed_abandoned.sql` | Agrega `closed_abandoned` al enum `conversation_status` — aplicada en staging vía SQL Editor |
| `apps/api/db/models.py` | `ConversationStatus` extendido con `closed_abandoned` |
| `apps/api/db/queries.py` | `get_stale_conversations` (pre-filtro SQL con COALESCE) + `mark_conversations_abandoned` (UPDATE idempotente) |
| `apps/api/services/cleanup.py` | Orquestador: itera tenants, mezcla timeouts por canal (overrideable en `extra.conversation_timeouts`), cierra abandonadas |
| `apps/api/main.py` | asyncio task `_cleanup_loop` en lifespan — arranca en startup, cancela en shutdown |
| `apps/api/core/config.py` | `cleanup_interval_seconds` (default 900 = 15 min, overrideable por env) |
| `apps/api/tests/test_cleanup.py` | 14 tests nuevos |

**Timeouts por canal (defaults):** email/zendesk/intercom → 72h · whatsapp/instagram/chatwoot → 48h · chat/widget → 24h

**Verificado en Railway staging:** log `cleanup_job_started interval_seconds=900` visible en startup ✅

**Suite total:** 331/331 verde. Ruff limpio.

---

## Sprint 7 — AOPs en DB + selector de intent + UI editor (en curso)

### Sub-PR 7.1 — Tablas DB + modelos + queries (commit `cd4ade8`)

| Área | Qué se hizo |
|---|---|
| `supabase/migrations/20260517000001_add_aops.sql` | Tablas `aops`, `aop_versions` (trigger immutabilidad), `intent_classifier_runs`; RLS en las tres |
| `apps/api/db/models.py` | `AopWorkspace`, `Aop`, `AopVersion`, `AopWithContent` (con `is_active`), `IntentClassifierRun` |
| `apps/api/db/queries.py` | `get_active_aops`, `get_aop_by_slug`, `create_aop`, `save_aop_version`, `insert_intent_classifier_run` |
| `apps/api/tests/test_aop_queries.py` | 19 tests unitarios |

### Sub-PR 7.2 — AOP compiler + TTL cache (commit `4ddcd68`)

| Área | Qué se hizo |
|---|---|
| `apps/api/aops/compiler.py` | `compile_aop` (6 bloques), `load_aop` con `TTLCache(maxsize=1000, ttl=60)`, `load_active_aops` |
| `apps/api/tests/test_aop_compiler.py` | 38 tests: cada `_render_*` + `compile_aop` + cache behavior |

### Sub-PR 7.3/7.4 — Nodo select_aop + cableado al grafo (commit `a3ae094`)

| Área | Qué se hizo |
|---|---|
| `apps/api/agents/nodes/select_aop.py` | Clasificador de intent con Haiku (tool-forced), fallback a 'default', `_should_reclassify` |
| `apps/api/agents/graph.py` | `select_aop` wired entre `load_conversation` y `retrieve_knowledge` |
| `apps/api/agents/state.py` | Campos AOP: `aop_slug`, `aop_version`, `intent_confidence`, `aop_locked_until_turn`, etc. |
| `apps/api/core/config.py` | `intent_min_confidence=0.60`, `intent_classifier_model=claude-haiku-4-5-20251001` |
| `apps/api/tests/test_select_aop_node.py` | 23 tests; `apps/api/tests/test_graph_e2e.py` actualizado |

**Degradación elegante:** tenants sin AOPs siguen usando `tenant_prompts` legacy sin cambio alguno.

### Sub-PR 7.5 — UI editor de AOPs (commit `bd8cce5`)

| Área | Qué se hizo |
|---|---|
| `apps/api/db/queries.py` | Queries de gestión: `list_aops`, `get_aop_by_id`, `toggle_aop_active`, `soft_delete_aop` |
| `apps/api/routers/aops.py` | CRUD completo + `POST /aops/validate` (preview del prompt compilado sin guardar) |
| `apps/api/main.py` | Router `aops_router` wired |
| `apps/web/lib/api/hooks/aops.ts` | `useAops`, `useAop`, `useCreateAop`, `useSaveAop`, `useToggleAop`, `useDeleteAop`, `useValidateAop` |
| `apps/web/components/aops/` | `AopList`, `AopEditor`, `AopEditView` |
| `apps/web/app/(dashboard)/tenants/[tenantId]/aops/` | Páginas list, new, `[aopId]` |
| `apps/web/components/nav/Sidebar.tsx` | Ítem "AOPs" en la nav |

**411/411 tests verde. TypeScript sin errores. Ruff limpio.**

### Sub-PR 7.6 — Eval harness + promote endpoint (commit `3b1546a`)

| Área | Qué se hizo |
|---|---|
| `apps/api/evals/__init__.py` | Módulo creado |
| `apps/api/evals/harness.py` | Runner puro (sin I/O): 10 tipos de aserciones (`compile_ok`, `prompt_contains`, `prompt_not_contains`, `prompt_min_length`, `skills_include`, `skills_not_include`, `max_iterations_gte`, `confidence_threshold_between`, `tool_count_matches_skills`, `frontmatter_has_key`), `load_fixtures`, `run_fixture`, `run_eval` con gate 80% |
| `apps/api/evals/fixtures/consulta_envio/` | 8 fixtures YAML: compilación, skills Shopify read, no L3, requiere email, nombre del procedimiento, max_iterations >= 3, escalation_triggers, tool defs match skills |
| `apps/api/evals/fixtures/default/` | 5 fixtures YAML: compilación, prompt no vacío, slug en frontmatter, confidence_threshold válido, no L3 |
| `apps/api/routers/aops.py` | `PATCH /aops/{id}/promote` — corre eval, bloquea si pass_rate < 80% (422 con detalles), copia contenido a production workspace si pasa |
| Fix | `response_model=None` en `DELETE /aops/{id}` (FastAPI assertion 204) |
| Tests | 39 nuevos (harness + promote endpoint) |

**Suite total: 450/450 verde. Ruff limpio.**

**Sprint 7 completado ✅** — AOPs en DB + compiler + selector de intent + UI editor + eval harness.

### Bugs post-Sprint 7 (sesión 16, 2026-05-17)

Validación e2e en staging del dashboard interno descubrió 3 bugs distintos. Los 3 se manifestaban con "Load failed" + Status 500 + CORS aparentemente roto (porque el error pasa antes del CORSMiddleware).

| Bug | Síntoma | Causa raíz | Fix |
|---|---|---|---|
| Tomar escalación falla | 500 + `escalations_assigned_user_id_tenant_id_fkey` | FK composite `(assigned_user_id, tenant_id) → users(id, tenant_id)` bloquea a super_admin (vive en su propio tenant) | [PR #56](https://github.com/Auyan-ai/platform/pull/56): FK simple a `users(id)` en `escalations` y `conversations` |
| Responder conversación falla | 500 + `messages_author_user_id_tenant_id_fkey` | Mismo problema en `messages.author_user_id` | [PR #57](https://github.com/Auyan-ai/platform/pull/57): FK simple a `users(id)` en `messages` |
| AOPs no carga | 500 + `UndefinedTableError: relation "aops" does not exist` | Migración `20260517000001_add_aops.sql` nunca se aplicó a staging — Railway deploya código pero NO SQL | Aplicada manualmente vía `psql` |

**Lección guardada en memoria:**
- Las migraciones de Supabase **no se auto-aplican** en deploy. Hay que correrlas a mano vía `psql` o SQL Editor.
- Nunca usar FK composite `(user_id, tenant_id) → users(id, tenant_id)` en tablas operacionales — bloquea a super_admin. Validar tenant en service layer, no en DB.

**CORS también:** `ALLOWED_ORIGINS` en Railway estaba sin `https://` prefix. Corregido manualmente a `http://localhost:3000,http://localhost:3001,https://auyan-web-staging.up.railway.app`.

**Ruff fix:** PR #55 — `per-file-ignores` para `evals/`, `scripts/` y `tests/` (S603 + E501 en strings de mensajes).

### Empezar aquí en la próxima sesión — usar **Sonnet**

1. **Sprint 8** — Agent Reasoning UI (ver sección más abajo)
   - 8.1: Migración `agent_reasoning_events` + `ReasoningTracker` service + emisión desde nodos
   - 8.2: Endpoints REST + SSE `/reasoning` y `/reasoning/stream`
   - 8.3: Componentes React (`AgentReasoningPanel`, `ReasoningPhase`, `ReasoningItem`, `ToolCallChip`)
   - 8.4: Integración en `TicketDetail` (dashboard interno) y `ClientTicketDetail` (dashboard tenant)

---

## Sprint 8 — Agent Reasoning UI (transparencia del agente)

**Objetivo:** Que los operadores (internos y tenants) puedan ver en tiempo real qué está pensando y haciendo el agente mientras procesa un ticket — sin necesidad de ir a Langfuse.

### Motivación

En los dashboards (interno y tenant) cada ticket tendrá un dropdown colapsable "Agent reasoning" que muestra las fases del agente secuencialmente con un checkmark al completarse, similar a la UI de Sierra/Decagon. Esto da:
- Observabilidad operativa sin salir del dashboard
- Contexto inmediato cuando hay que revisar una respuesta
- Confianza del tenant en que el agente trabajó correctamente
- Debugging rápido sin tener que buscar trace IDs en Langfuse

### Diseño de la UI

El dropdown muestra tres secciones con ícono propio:

```
👁  Supervisors          ✓
    Detect abuse         ✓
    Observations         ✓

📖  Decisions            ✓
    [AccessCustomerHistory]   ✓   ← chip expandible con los args JSON
         { "email": "•••@•••", "orderId": "1234" }
    Searched [TroubleshootingGuide]  ✓

🔧  Responses            ✓
    Start troubleshooting  ✓
```

- Las secciones aparecen en orden mientras el agente trabaja (streaming)
- Cada ítem tiene checkmark al completarse
- Los tool calls son chips clickeables que expanden los args (con PII ofuscado en vista tenant)
- En el dashboard interno se ve el JSON completo; en el dashboard tenant los valores sensibles se enmascaran (`•••`)

### Arquitectura técnica

#### Backend

**1. Tabla nueva: `agent_reasoning_events`**
```sql
CREATE TABLE agent_reasoning_events (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenants(id),
  ticket_id   uuid NOT NULL REFERENCES tickets(id),
  phase       text NOT NULL,          -- 'supervisor' | 'decision' | 'response'
  event_type  text NOT NULL,          -- 'check' | 'tool_call' | 'tool_result' | 'choice'
  label       text NOT NULL,          -- texto legible: "Detect abuse", "shopify.get_order_by_email"
  detail      jsonb,                  -- args del tool call, resultado, etc.
  status      text NOT NULL DEFAULT 'pending',  -- 'pending' | 'done' | 'error'
  seq         integer NOT NULL,       -- orden dentro del ticket
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  deleted_at  timestamptz
);
```

**2. Emisión de eventos desde los nodos del grafo**
- Cada nodo llama a `reasoning_tracker.emit(ticket_id, phase, event_type, label, detail)` al iniciar y al terminar
- `reasoning_tracker` es un servicio liviano que inserta en Supabase (async, no bloquea el grafo)
- Nodos que emiten:
  - `load_tenant_context` → fase supervisor: "Load context"
  - `reason` → fase supervisor: "Observations"; fase decision: cada tool_use que proponga el LLM
  - `execute_skill` → fase decision: resultado del tool call (done/error)
  - `respond` → fase response: tipo de respuesta elegida
  - `escalate` → fase response: "Escalate to human" + razón

**3. API endpoints**
- `GET /tickets/{ticket_id}/reasoning` — historial completo (REST, para cargar al abrir el dropdown)
- `GET /tickets/{ticket_id}/reasoning/stream` — SSE para actualizaciones en tiempo real mientras el agente trabaja

#### Frontend (`apps/web`)

**Componentes:**
- `<AgentReasoningPanel ticket_id>` — contenedor colapsable (toggle dropdown)
  - `<ReasoningPhase phase label items>` — sección con ícono (Supervisors / Decisions / Responses)
    - `<ReasoningItem label status>` — fila con checkmark animado
      - `<ToolCallChip label args masked?>` — chip expandible para tool calls

**Comportamiento:**
- Panel empieza colapsado; se expande con un click
- Si el agente sigue activo, se conecta al SSE y agrega ítems en tiempo real con animación
- Si el ticket ya está cerrado, carga el historial via REST y muestra todo estático
- En vista tenant: args de tool calls se enmascaran (regex sobre campos `email`, `phone`, `token`, `card`)
- En vista interna: se ve todo el JSON completo

### Sub-PRs propuestos

| Sub-PR | Qué incluye | Modelo |
|--------|-------------|--------|
| 8.1 | Migración SQL `agent_reasoning_events` + `ReasoningTracker` service + emisión desde nodos + tests | Sonnet |
| 8.2 | Endpoint REST + SSE `/reasoning` y `/reasoning/stream` + tests de integración | Sonnet |
| 8.3 | Componentes React: `AgentReasoningPanel`, `ReasoningPhase`, `ReasoningItem`, `ToolCallChip` + Storybook | Sonnet |
| 8.4 | Integración en `TicketDetail` (dashboard interno) + `ClientTicketDetail` (dashboard tenant) con PII masking | Sonnet |

### Criterio de éxito

- Abrir un ticket en el dashboard y ver, en tiempo real, las fases del agente completándose con checkmarks
- Al expandir un chip de tool call, ver los argumentos (enmascarados en vista tenant)
- Sin impacto en latencia del agente (la emisión es async fire-and-forget)
- Sin acceso cruzado: tenant A no ve razonamientos de tenant B (RLS en `agent_reasoning_events`)

### Sub-PR 8.1 — Migración + ReasoningTracker + emisión desde nodos (commit en [PR #59](https://github.com/Auyan-ai/platform/pull/59))

| Área | Qué se hizo |
|---|---|
| `supabase/migrations/20260517000002_add_agent_reasoning_events.sql` | Tabla `agent_reasoning_events` con RLS, índice `(conversation_id, seq)`, trigger `updated_at` |
| `apps/api/services/reasoning.py` | `ReasoningTracker`: `emit()` fire-and-forget vía `asyncio.create_task`, falla silencioso — no bloquea el grafo |
| `apps/api/db/models.py` | Literals `ReasoningPhase`, `ReasoningEventType`, `ReasoningStatus` + Pydantic `AgentReasoningEvent` |
| `apps/api/db/queries.py` | `insert_reasoning_event` (MAX(seq)+1 subquery) + `list_reasoning_events` |
| `apps/api/agents/dependencies.py` | Campo `reasoning_tracker: ReasoningTracker` |
| `apps/api/agents/state.py` | 7 campos supervisor: `supervisor_verdict`, `supervisor_reason`, `supervisor_reject_kind`, `supervisor_retried`, `supervisor_model_used`, `supervisor_tokens_in`, `supervisor_tokens_out` |
| Nodos | `load_tenant_context`, `reason`, `execute_skill`, `respond`, `escalate` emiten eventos a `reasoning_tracker` |
| `apps/api/tests/conftest.py` | `FakeReasoningTracker` + `fake_reasoning_tracker` fixture + `fake_deps` actualizado |
| `apps/api/tests/test_reasoning_tracker.py` | 7 tests: emit sin loop, DB failure silente, task creation, emit en nodo |

### Sub-PR 8.2 — Endpoints REST + SSE (commit en [PR #59](https://github.com/Auyan-ai/platform/pull/59))

| Área | Qué se hizo |
|---|---|
| `apps/api/routers/reasoning.py` | `GET /conversations/{id}/reasoning` (historial REST) + `GET /conversations/{id}/reasoning/stream` (SSE, poll cada 1 s, max 5 min, Last-Event-ID para reconexión) |
| `apps/api/main.py` | `reasoning_router` wired + `ReasoningTracker()` instanciado en lifespan |

### Sub-PR 8.3 — Componentes React (commit en [PR #59](https://github.com/Auyan-ai/platform/pull/59))

| Área | Qué se hizo |
|---|---|
| `apps/web/lib/api/hooks/reasoning.ts` | `useReasoningEvents` (TanStack Query, staleTime 5s) + `useReasoningStream` (fetch+ReadableStream — EventSource no soporta headers auth) |
| `apps/web/lib/api/query-keys.ts` | `reasoning.events(tenantId, conversationId)` |
| `apps/web/components/reasoning/ToolCallChip.tsx` | Chip expandible con ChevronRight/Down, detalle JSON en `<pre>`, PII masking por regex |
| `apps/web/components/reasoning/ReasoningItem.tsx` | Fila con `StatusIcon`: Check=done, X=error, Clock=pending (animate-pulse) |
| `apps/web/components/reasoning/ReasoningPhase.tsx` | Agrupa eventos por fase: Eye=supervisor, GitBranch=decision, MessageSquare=response; ✓ cuando allDone |
| `apps/web/components/reasoning/AgentReasoningPanel.tsx` | Panel colapsable: REST siempre + SSE solo cuando `open && isActive`; spinner cuando activa+loading |

### Sub-PR 8.4 — Integración en dashboards (commit en [PR #59](https://github.com/Auyan-ai/platform/pull/59))

| Área | Qué se hizo |
|---|---|
| `apps/web/components/inbox/ConversationDetail.tsx` | Prop `maskPII?: boolean` + `isActive` desde `conversation.status`; `AgentReasoningPanel` entre mensajes y composer |
| `apps/web/app/clients/.../conversations/[id]/page.tsx` | Pasa `maskPII` a `ConversationDetail` para vista tenant |

### Sub-PR 8.5 — Supervisor pattern (commit en [PR #59](https://github.com/Auyan-ai/platform/pull/59))

| Área | Qué se hizo |
|---|---|
| `apps/api/agents/nodes/supervise.py` | `needs_supervision`: True si L2/L3 pending o `require_supervision` en config; `_select_supervisor_model`: Opus para L3, Sonnet resto; primer rechazo táctico → retry con feedback; rechazo estructural/segundo → `escalation_reason` |
| `apps/api/agents/graph.py` | `route_after_reason` verifica `needs_supervision`; `route_after_supervise`: approve→execute/respond/escalate, reject con `escalation_reason`→escalate, sin `escalation_reason`→reason |
| `apps/api/tests/test_supervise_node.py` | 16 tests: `needs_supervision`, approve, tactical, structural, Opus/Sonnet selection, token accumulation, event emission |

**Suite total: 478/478 verde. tsc --noEmit limpio.**

### Bugs encontrados al validar Sprint 8 en staging (sesión 18, 2026-05-18)

Tres bugs distintos descubiertos al mandar el primer webhook real contra staging — todos detectables solo con E2E, no con tests unitarios:

| Bug | Síntoma | Causa raíz | Fix |
|---|---|---|---|
| Migración no aplicada | `function update_updated_at_column() does not exist` | la función estándar del repo es `set_updated_at` en `public`; `update_updated_at_column` solo existe en schema `storage` | Migración corregida; aplicada manualmente en staging |
| 0 filas en `agent_reasoning_events` | webhook 200 OK pero la tabla quedaba vacía | `json.dumps(detail)` + cast `$6::jsonb` hacían que asyncpg aplicara su encoder JSONB (`json.dumps`) sobre el string ya serializado → double encoding → al leer, decoder devolvía un string → `dict(string)` reventaba en silencio (background task fire-and-forget tragaba el error) | [PR #62](https://github.com/Auyan-ai/platform/pull/62): pasar dict/None directos sin cast, patrón que ya usaba `create_message`. Mismo bug latente en `create_aop`/`save_aop_version` (Sprint 7) — corregidos también |
| Hilo sin mensaje del agente al escalar | escalación creada pero el cliente no veía nada del agente — solo el cambio de status | schema `RESPOND_OR_ESCALATE_TOOL` marcaba `response_text` obligatorio solo para `decision='respond'` | [PR #63](https://github.com/Auyan-ai/platform/pull/63): `response_text` obligatorio siempre — para escalate es el mensaje de cortesía/handoff |

**Bug secundario diagnosticado en el camino:** `asyncio.get_event_loop()` desde una función síncrona en Python 3.12 lanza `RuntimeError` que el `except RuntimeError: pass` silenciaba. Aunque NO era el bug principal (el JSONB era el principal), también era un riesgo real porque Dockerfile usa `python:3.12-slim` y el entorno local Python 3.11. [PR #60](https://github.com/Auyan-ai/platform/pull/60): `get_running_loop()` que es el patrón correcto para Python 3.10+.

**Workaround Railway auto-deploy:** el GitHub App de Railway no firea builds automáticamente — disparados manualmente con `environmentTriggersDeploy` por GraphQL (memoria `reference_railway_deploy_trigger.md`).

### Validación E2E en staging (sesión 18)

| Conversación | Mensaje | Decisión | Reasoning events | Verificación |
|---|---|---|---|---|
| `59a79302` | "¿dónde está mi pedido?" | respond | 3 (Load context → Decision: respond → Agent responded) | Respuesta del agente pidiendo email/número ✅ |
| `e18ae88d` | "quiero hablar con un humano" | escalate | 3 (Load context → Decision: escalate → Escalated to human) | Mensaje de handoff del agente + escalation creada ✅ |
| `f856a607` | "¿política de devoluciones?" | escalate (KB vacía) | 5 (incluye tool_call shopify.get_shop_policies pending → done) | Skill ejecutada, escalación porque KB no tiene info ✅ |

**Sprint 8 completado ✅** — Agent Reasoning UI + Supervisor pattern + handoff message — validado end-to-end en staging.

### Pendientes para próximas sesiones

- ~~**Probar conversación multi-turno**~~ → validado en sesión 19. Ver tabla abajo.
- **Endpoint debug `/health/reasoning-debug` removido** — usado solo para diagnosticar el bug de JSONB, ya no hace falta.

### Empezar aquí en la próxima sesión — usar **Sonnet**

1. ~~Probar conversación multi-turno~~ ✅
2. **Sprint 9** — Skills L2 + permissions + audit log con PII + idempotency

---

## Sesión 19 — Context engineering analysis + KB seeding + multi-turno validado (2026-05-18)

**Sin cambios al grafo** — sesión de análisis + infraestructura de pruebas + validación multi-turno.

### Lo que se hizo

| Área | Qué se hizo |
|---|---|
| Análisis context engineering | Revisión del artículo de Neil Rahilly (Sierra) contra el codebase actual. Ver `docs/architecture-agent-v2.md` sección 19. |
| `apps/api/scripts/seed_kb.py` | Script para poblar la KB de un tenant con contenido fantasioso de Lunaria (5 documentos, 20 chunks). Uso: `poetry run python -m scripts.seed_kb --clear` |
| `docs/architecture-agent-v2.md` sección 19 | Análisis completo de gaps de context engineering + roadmap de detección de alucinaciones |
| `docs/progress.md` | Gaps priorizados añadidos a deuda técnica |

### KB de Lunaria — datos fantasiosos para anti-alucinación

El contenido de `seed_kb.py` usa datos deliberadamente impares e inventados:
- Devoluciones: **49 días** (7 lunas llenas), reembolso solo en **Crédito Estelar**
- Envío gratis desde **€137**, modalidades: **Constelación Express / Tránsito Lunar / Viaje Estelar**
- Tracking con código **LN-XXXXXXX** vía sistema **Órbita**
- Precios impares: €137, €189, €743, €311, €521, €1.107...
- Membresía **Guardianas de la Luna** a **€89/año** con 3 niveles
- Si el agente dice "30 días" o "envío gratis sin mínimo" → **alucinación confirmada**

### Multi-turno validado en staging (sesión 19)

| Turno | Mensaje | Decisión | Resultado |
|---|---|---|---|
| 1 | "¿Cómo funciona el programa Guardianas de la Luna?" | respond | Respuesta completa: €89/año, 15%, 72h, Colección Guardianas ✅ |
| 2 | "¿Y cuánto cuesta la membresía anual?" | respond | "Ya te lo comenté justo antes 😊 ...€89/año" — contexto del turno anterior usado correctamente ✅ |

**`feat(webhook): conversation_id` para multi-turno** — PR #66 mergeado. El script `send_test_webhook.py` acepta `--conversation-id` y muestra hint tras cada llamada.

**Alucinación detectada y documentada:** el agente mezcla "rider habitual" + 🏂 del Shopify de snowboards con el KB de joyería de Lunaria. Causa: conflicto entre la tienda Shopify de prueba (auto-generada como "Lunaria Boards" snowboards) y el KB de joyería. Pendiente en deuda técnica.

### Deuda técnica añadida en sesión 19

- **Conflicto Shopify snowboards vs KB joyería** — la tienda de prueba `lunaria-eleq1sc5.myshopify.com` fue auto-generada por Shopify como tienda de snowboards. El agente mezcla datos de Shopify con el KB de Lunaria joyería. Fix: actualizar el contenido de la tienda Shopify de prueba O crear una regla en el AOP que priorice el KB para preguntas de política/programa y use Shopify solo para datos de pedidos/clientes específicos.

---

## Sesión 20 — Sprint 9.1 + 9.2 (2026-05-18)

### Sprint 9.1 — Idempotency ([PR #68](https://github.com/Auyan-ai/platform/pull/68)) ✅ mergeado

Previene duplicación de mensajes/escalaciones cuando un canal reintenta un webhook por timeout o error 5xx.

| Área | Qué se hizo |
|---|---|
| `supabase/migrations/20260518000000_add_idempotency_keys.sql` | Tabla `idempotency_keys` con TTL 24h y `UNIQUE(tenant_id, key)`. **Aplicada en staging.** |
| `apps/api/db/models.py` | `IdempotencyRecord` |
| `apps/api/db/queries.py` | `try_insert_idempotency_key`, `get_idempotency_record`, `complete_idempotency_key`, `delete_idempotency_key` |
| `apps/api/routers/webhooks.py` | Header `X-Idempotency-Key` opcional: claim → proceso → complete / delete en error |
| `apps/api/tests/test_idempotency.py` | 10 tests — todos los escenarios cubiertos |

**Flujo:** primera petición (pending → done + respuesta cacheada) · duplicado → 200 desde caché sin re-procesar · en vuelo → 409 · error de procesamiento → delete para permitir reintento.

### Sprint 9.2 — Skills L2 + permission gate ([PR #69](https://github.com/Auyan-ai/platform/pull/69)) ✅ pendiente merge

Dos skills L2 nuevas de Shopify + gate de permisos en el nodo `execute_skill`.

| Área | Qué se hizo |
|---|---|
| `integrations/shopify.py` | `add_order_note` + `tag_order` (métodos write L2) |
| `skills/shopify/add_order_note.py` | Skill L2: añade/reemplaza la nota interna de un pedido |
| `skills/shopify/tag_order.py` | Skill L2: merge no-destructivo de tags en un pedido (ej: `return-requested`, `damaged`) |
| `agents/nodes/execute_skill.py` | Gate: L2 requiere `allow_l2_skills: true` en `tenant_config.extra`; L3 bloqueado siempre (Sprint 10) |
| `tests/skills/test_shopify_l2_skills.py` | 14 tests nuevos |
| `tests/test_execute_skill_node.py` | 6 tests nuevos del permission gate |

**Para activar L2 en un tenant:**
```sql
UPDATE tenant_configurations
SET extra = extra || '{"allow_l2_skills": true}'::jsonb
WHERE tenant_id = '<uuid>';
```

**Suite total: 510/510 verde. Ruff limpio.**

---

## Sesión 21 — Sprint 9.3 Audit log con PII (2026-05-18)

### Sprint 9.3 — Audit log de skills con pseudonimización PII ([PR #71](https://github.com/Auyan-ai/platform/pull/71)) ✅ mergeado

Registra toda ejecución de skill (L1/L2/L3) con PII pseudonimizado. Decisión confirmada: hashing en app Python, no en pgcrypto, para que el salt nunca aparezca en logs de Postgres.

| Área | Qué se hizo |
|---|---|
| `supabase/migrations/20260518000001_add_skill_audit_log.sql` | Tabla `tenant_secrets` (salt PII por tenant, seeded para tenants existentes) + `skill_audit_log` con RLS e índices. **Aplicada manualmente en staging.** |
| `apps/api/services/pii.py` | `redact_inputs` (email→`<email:hash16>`, phone→`***-1234`, name→`J. P.`) + `hash_inputs` sha256 canónico para forense |
| `apps/api/services/audit.py` | `AuditLogger` fire-and-forget — mismo patrón que `ReasoningTracker`. Stateless, instanciar una vez en startup |
| `apps/api/db/models.py` | `TenantSecret`, `SkillAuditLog`, `SkillAuditStatus` |
| `apps/api/db/queries.py` | `get_tenant_pii_salt` (upsert lazy), `insert_skill_audit_log`, `list_skill_audit_log` |
| `apps/api/agents/dependencies.py` | Campo `audit_logger: AuditLogger` en `AgentDependencies` |
| `apps/api/agents/nodes/execute_skill.py` | Emite al audit log con `latency_ms` en tres puntos: permission gate (→`rejected_by_permissions`), skill failure (→`failed`), éxito (→`success`) |
| `apps/api/main.py` | `AuditLogger()` instanciado en lifespan junto a `ReasoningTracker` |
| Tests | 27 nuevos: 17 PII unit, 5 AuditLogger (fire-and-forget + redacción real), 5 execute_skill audit |

**Política PII aplicada:**
- Email: `sha256(valor + salt_tenant)[:16]` → `<email:a3f1b2c4d5e6f7a8>`
- Teléfono: últimos 4 dígitos → `***-5678`
- Nombre: iniciales → `A. G. L.`
- IDs, order numbers, textos libres: sin cambio

**Suite total: 537/537 verde. Ruff limpio.**

---

## Sesión 22 — Sprint 9.4 Cache invalidation AOPs (2026-05-18)

### Sprint 9.4 — AOP cache invalidation vía Postgres NOTIFY ([PR #73](https://github.com/Auyan-ai/platform/pull/73)) ✅ en revisión

Invalida el cache de AOPs en todos los workers de Railway sin Redis.

| Área | Qué se hizo |
|---|---|
| `apps/api/aops/compiler.py` | `invalidate_aop_cache(tenant_id, slug, workspace)` — elimina entrada del `_AOP_CACHE` local |
| `apps/api/db/queries.py` | `notify_aop_cache_invalidated(conn, tenant_id, slug, workspace)` — emite `pg_notify` con JSON payload dentro de la transacción activa |
| `apps/api/services/aop_listener.py` | `AopCacheListener` — conexión asyncpg dedicada (fuera del pool), `LISTEN aop_cache_invalidated`, keep-alive SELECT 1 cada 30s, callback `_on_notify` → `invalidate_aop_cache` |
| `apps/api/routers/aops.py` | PUT/toggle/delete/promote: invalidan cache local + emiten `pg_notify` dentro del `tenant_scope` |
| `apps/api/main.py` | `AopCacheListener` instanciado en lifespan; `await aop_listener.stop()` en shutdown |
| Tests | 12 tests nuevos (549 total) |

**Flujo:** Worker A edita AOP → `pg_notify` en transacción → commit → Postgres entrega notificación a todos los workers con LISTEN → `_on_notify` → `invalidate_aop_cache`. Delay: latencia de red Postgres, sin TTL de espera.

**Nota:** conexión LISTEN es separada del pool (asyncpg no puede hacer queries normales mientras escucha en una misma conexión).

**Suite total: 549/549 verde. Ruff limpio.**

---

## Sesión 22 (cont.) — Sprint 9.5 Nudges de conversación (2026-05-18)

### Sprint 9.5 — Nudges antes del cierre automático ([PR #74](https://github.com/Auyan-ai/platform/pull/74)) ✅ en revisión

Envía un mensaje recordatorio al cliente antes de cerrar la conversación por inactividad. Opt-in por tenant, sin reiniciar el timer del cierre.

| Área | Qué se hizo |
|---|---|
| `supabase/migrations/20260518000003_add_nudged_at.sql` | Columna `nudged_at timestamptz` en `conversations`. **Aplicar manualmente en staging.** |
| `apps/api/db/models.py` | `nudged_at: datetime \| None` en `Conversation` |
| `apps/api/db/queries.py` | `get_nudge_candidates`, `mark_conversations_nudged`, `nudged_at` en todos los SELECT de conversaciones |
| `apps/api/services/cleanup.py` | `_build_nudge_cutoffs` (ventana de nudge por canal), `_nudge_for_tenant` (inserta mensaje + marca `nudged_at`), `run_abandoned_cleanup` ejecuta nudge antes del cierre |
| Tests | 11 tests nuevos (560 total) |

**Config por tenant (en `extra`):**
```json
{
  "nudge_enabled": true,
  "nudge_before_seconds": 3600,
  "nudge_message": "¿Pudimos ayudarte? Si necesitas algo más, estamos aquí."
}
```

**Flujo:** Cleanup (cada 15min) → busca conversaciones en ventana `[timeout - nudge_before, timeout]` con `nudged_at IS NULL` → inserta mensaje `role=agent_ai` sin tocar `last_message_at` → setea `nudged_at` → luego corre el cierre normal.

**Suite total: 560/560 verde. Ruff limpio.**

### Empezar aquí en la próxima sesión — usar **Sonnet**

1. Mergear [PR #74](https://github.com/Auyan-ai/platform/pull/74) si CI pasa (aplicar migración `nudged_at` en staging)
2. **Sprint 10** — Skills L3 + human approval mode
   - Skill `shopify.cancel_order` (L3 — acción destructiva con confirmación)
   - Human approval mode: antes de ejecutar L3, el agente crea una escalación con `requires_approval=True` y espera respuesta del agente humano desde el dashboard
   - Gate en `execute_skill`: L3 → check `allow_l3_skills` + approval flow
