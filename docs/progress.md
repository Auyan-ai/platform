# Auyan — Estado del proyecto

_Última actualización: 2026-05-15 (sesión 7 — Sprint 3 completo, apps/web desplegado en staging)_

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

### Sub-PR 3.7 — completado ([PR #24](https://github.com/Auyan-ai/platform/pull/24))

| Área | Qué se hizo |
|---|---|
| `apps/web/Dockerfile` | Build multistage pnpm workspace desde raíz, Next.js standalone, runner mínimo |
| `next.config.ts` | `output: standalone` + `outputFileTracingRoot` para monorepo |
| `api-types.ts` | Regenerado — incluye `GET /tenants/admin/list` tipado |
| `useAdminTenants` | Migrado de fetch manual a openapi-fetch tipado |
| Railway | Servicio `auyan-web` creado, dominio `https://auyan-web-staging.up.railway.app` |
| `ALLOWED_ORIGINS` | Actualizado en el servicio API de Railway para incluir la URL web |

### Empezar aquí en la próxima sesión — usar **Sonnet**

1. Sprint 4: dashboard cliente por tenant (`/clients/`) — vista read-only para el cliente final
2. Deuda: CI con GitHub Actions (ruff + pytest + tsc en cada PR)
3. Deuda: diseño visual del dashboard (el UX funciona pero es feo — pendiente de refinar)

### Bloqueos NO arrastrados de Sprint 1 (siguen pendientes)

- [ ] **Agregar créditos a OpenAI** — el agente sigue escalando por `429 insufficient_quota` en `retrieve_knowledge`. Bloquea respuesta real, no bloquea el refactor.
- [ ] **Sincronizar `WEBHOOK_SECRET` local** con el de Railway.

---

## Deuda técnica registrada para Sprint 2+

- **Script de upload de vars a Railway debe stripear comentarios inline** — el script actual toma todo lo que hay después del `=`, incluyendo `# comentarios`. Reescribirlo para parsear `.env` igual que bash.
- ~~**Refactor de services + routers al paradigma asyncpg**~~ → reinterpretado como "agregar endpoints admin faltantes + auth real". En curso (Sprint 2).
- ~~**`poetry.lock` ausente**~~ → resuelto en sesión 4 ([commit 6d1023f](https://github.com/Auyan-ai/platform/commit/6d1023f)).
- **Rol `auyan_backend` en Supabase con `NOBYPASSRLS`** — actualmente conectamos con `postgres` (bypass RLS). La defensa multi-tenant depende solo de `WHERE tenant_id = $1` y el GUC por request.
- **Tests de integración contra Postgres+pgvector real** — hoy todo es unit con mocks.
- **Integraciones de canales** (`chatwoot.py`, `zendesk.py`, `shopify.py`) son clientes HTTP esqueleto — cablear con el flujo del agente.
- **CI ausente** — hay `.github/workflows/` vacío. Configurar GitHub Actions con ruff + mypy + pytest sobre cada PR.
- ~~**`.claude/` no está en `.gitignore`**~~ → resuelto en sesión 6 ([PR #12](https://github.com/Auyan-ai/platform/pull/12)).
- **Errores mypy preexistentes** en `db/models.py`, `db/queries.py`, `db/client.py`, `core/config.py` (14 errors `[type-arg]` y `[no-any-return]`). No bloquean la suite pero ensucian el typecheck.

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
