# Arquitectura — Dashboard interno (`apps/web`)

_Diseño aprobado al inicio del Sprint 3 (2026-05-14). Este documento es la referencia de los sub-PRs del sprint. Cualquier cambio de fondo se discute y se versiona acá antes de modificar código._

---

## 1. Contexto y objetivo

El backend ya expone 10 endpoints administrativos protegidos con Supabase JWT (Sprint 2, PR #14). Sprint 3 construye `apps/web`: una Next.js app que consume esos endpoints para que los **agentes humanos de Auyan** (rol `super_admin`) gestionen conversaciones y escalaciones de los tenants cuyo flujo de soporte hostea Auyan.

**No está en scope para este sprint:**

- `/clients/*` (dashboard del tenant cliente con rol `tenant_admin` / `tenant_agent`). Misma app, distinto layout, se construye en Sprint 4.
- Realtime via Supabase Realtime — bloqueado por la deuda del rol `auyan_backend` con `NOBYPASSRLS` y policies con `auth.uid()`. Sprint 3 usa polling.
- Chat widget (`apps/widget`).
- Integraciones de canales (Chatwoot, Zendesk, Shopify) — independientes.

---

## 2. Decisiones tomadas

| Decisión | Elegido | Alternativas descartadas | Razón |
|---|---|---|---|
| Alcance Sprint 3 | Solo `/dashboard/*` (super_admin) | Solo `/clients/*`; ambos en paralelo | Es la operación core del BPO; un solo layout, un solo rol, un solo flow de auth |
| Framework | Next.js 15 App Router + TypeScript strict | Pages Router, Remix, SPA Vite | Ya definido en CLAUDE.md |
| Package manager | pnpm + workspaces | npm, yarn, bun | Monorepo Next.js + paquetes compartidos; estándar de facto |
| UI | shadcn/ui + Tailwind v4 | Mantine v8, Chakra v3 | Headless, copy-paste, librería de facto en 2026, fácil branding por tenant |
| Auth client | `@supabase/ssr` | `@supabase/auth-helpers-nextjs` | Auth-helpers está deprecated; SSR maneja cookies httpOnly limpias |
| Data fetching | TanStack Query v5 (cliente) + fetch en RSC (shell) | Solo RSC con revalidate; SWR | Inbox necesita refetch/poll/optimistic; RSC se queda para shells iniciales |
| Forms | react-hook-form + zod | Formik, vanilla | Validación tipada coherente con Pydantic del API |
| Tipos del API | `openapi-typescript` automático contra `/openapi.json` | Tipos a mano en `packages/shared`; tRPC | Sin drift FE/BE; un solo source of truth (Pydantic genera schema → TS genera tipos) |
| HTTP client | `openapi-fetch` | axios, fetch crudo, ofetch | Integra directo con los tipos de `openapi-typescript` |
| Realtime (MVP) | Polling con TanStack Query (`refetchInterval`) | Supabase Realtime; SSE desde API | Realtime requiere RLS posicionadas — deuda no cerrada |
| Tests | Vitest (unit/component) + Playwright (e2e crítico) | Jest, Cypress | Vitest es más rápido y coherente con el stack moderno |
| Lint/format | Biome | ESLint + Prettier | Un solo binario, más rápido, menos config |
| Despliegue | Railway, app separada | Vercel, Fly.io | Consistencia con `apps/api` |

---

## 3. Stack consolidado

```
Next.js 15  +  TypeScript strict  +  Tailwind v4  +  shadcn/ui
@supabase/ssr  +  TanStack Query v5  +  openapi-fetch  +  openapi-typescript
react-hook-form + zod  |  Vitest + Playwright  |  Biome
pnpm workspaces  |  Railway
```

---

## 4. Auth flow

```
Browser                    Next.js (apps/web)              Supabase Auth         FastAPI (apps/api)
  |                              |                              |                        |
  |--/login (email+password)---->|                              |                        |
  |                              |--signInWithPassword--------->|                        |
  |                              |<--{user, session, jwt}-------|                        |
  |<--set-cookie (sb-* httpOnly)-|                              |                        |
  |                              |                              |                        |
  |--GET /dashboard------------->|                              |                        |
  |                              |--middleware: getSession      |                        |
  |                              |  (refresh si está por vencer)|                        |
  |                              |--RSC fetch /conversations--->|--Bearer <jwt>--------->|
  |                              |                              |  X-Tenant-Id: <uuid>   |
  |                              |<--JSON-----------------------|<-----------------------|
  |<--HTML-----------------------|                              |                        |
```

**Reglas:**

- `@supabase/ssr` guarda la sesión en cookies httpOnly (`sb-<project>-auth-token`).
- `middleware.ts` corre en cada request: refresca el access_token si está por expirar y redirige a `/login` si no hay sesión.
- `super_admin` accede solo a `/dashboard/*`. Si entra a `/clients/*` (que aún no existe), redirect a `/dashboard`.
- En el cliente, TanStack Query usa un hook `useApiClient()` que lee el token del cliente browser de Supabase y arma el wrapper tipado.
- El header `X-Tenant-Id` se pone en cada request del `/dashboard/tenants/[tenantId]/*` leyendo el segmento de URL — el tenant activo vive en la URL, no en estado global, así el deep-linking funciona y el browser back también.

**Roles del JWT:** los pobla el seed de Supabase (ver `db/queries.get_user_for_auth`). El rol vive en `public.users.role`; el JWT solo trae `sub` (user_id) y el lookup contra `public.users` resuelve role + tenant.

---

## 5. Estructura de carpetas

```
platform/
├── package.json                       # workspaces: apps/*, packages/*
├── pnpm-workspace.yaml
├── biome.json
├── apps/
│   ├── api/                           # FastAPI (existente)
│   └── web/                           # NUEVO
│       ├── app/
│       │   ├── (auth)/
│       │   │   ├── login/page.tsx
│       │   │   └── layout.tsx
│       │   ├── (dashboard)/                       # super_admin only
│       │   │   ├── layout.tsx                     # sidebar + tenant switcher
│       │   │   ├── page.tsx                       # overview cross-tenant
│       │   │   └── tenants/[tenantId]/
│       │   │       ├── layout.tsx                 # contexto del tenant activo
│       │   │       ├── conversations/
│       │   │       │   ├── page.tsx               # lista
│       │   │       │   └── [id]/page.tsx          # detalle + responder
│       │   │       ├── escalations/page.tsx
│       │   │       └── settings/page.tsx
│       │   ├── layout.tsx                         # root: providers (Query, Theme)
│       │   └── globals.css
│       ├── components/
│       │   ├── ui/                                # shadcn primitives
│       │   ├── inbox/
│       │   │   ├── ConversationList.tsx
│       │   │   ├── ConversationDetail.tsx
│       │   │   └── MessageComposer.tsx
│       │   ├── escalations/
│       │   │   ├── EscalationQueue.tsx
│       │   │   └── EscalationCard.tsx
│       │   ├── tenant-switcher/TenantSwitcher.tsx
│       │   └── auth/LoginForm.tsx
│       ├── lib/
│       │   ├── supabase/
│       │   │   ├── client.ts                      # browser
│       │   │   ├── server.ts                      # RSC / Route Handlers
│       │   │   └── middleware.ts                  # refresh + redirects
│       │   ├── api/
│       │   │   ├── client.ts                      # openapi-fetch wrapper
│       │   │   ├── hooks/
│       │   │   │   ├── conversations.ts           # useConversations, useConversation, useReply...
│       │   │   │   ├── escalations.ts
│       │   │   │   └── tenants.ts
│       │   │   └── query-keys.ts                  # convención de keys de TanStack
│       │   └── utils.ts
│       ├── middleware.ts
│       ├── next.config.ts
│       ├── tailwind.config.ts
│       ├── tsconfig.json
│       ├── biome.json (extends root)
│       ├── components.json                        # shadcn config
│       └── package.json
└── packages/
    └── shared/                        # NUEVO
        ├── src/
        │   ├── api-types.ts           # generado por openapi-typescript
        │   ├── index.ts
        │   └── enums.ts               # ChannelType, ConversationStatus... (manual, fuente única)
        ├── package.json
        └── tsconfig.json
```

Convenciones:

- Cada componente client-side empieza con `'use client'`. RSC es el default.
- `lib/api/hooks/*` exporta hooks de TanStack Query con keys normalizadas (`['conversations', tenantId, filters]`).
- `lib/supabase/server.ts` se usa solo desde RSC y Route Handlers — nunca importado por cliente.
- shadcn se instala con CLI; los primitives quedan en `components/ui/` (committed, no node_modules).

---

## 6. Generación de tipos del API

`openapi-typescript` consume el schema de FastAPI y produce un archivo TS con todos los `paths` y `components`.

```jsonc
// package.json (root) — scripts
{
  "scripts": {
    "gen:api-types": "openapi-typescript ${API_URL:-http://localhost:8000}/openapi.json -o packages/shared/src/api-types.ts"
  }
}
```

Wrapper de cliente:

```ts
// apps/web/lib/api/client.ts
import createClient from 'openapi-fetch'
import type { paths } from '@auyan/shared'

export function apiClient(jwt: string, tenantId?: string) {
  return createClient<paths>({
    baseUrl: process.env.NEXT_PUBLIC_API_URL!,
    headers: {
      Authorization: `Bearer ${jwt}`,
      ...(tenantId ? { 'X-Tenant-Id': tenantId } : {}),
    },
  })
}
```

**Regla operativa:** cualquier PR que modifique schemas/respuestas del API corre `pnpm gen:api-types` y comitea el diff. Sub-PR del Sprint 3.7 añade verificación en CI (drift = build rojo).

---

## 7. Data fetching y polling

| Vista | Pattern | Refetch |
|---|---|---|
| Login | client-only, sin Query | — |
| Layout `/dashboard` | RSC shell (sidebar) + cliente para tenant switcher | — |
| Overview (`/dashboard`) | Cliente (TanStack Query) | manual |
| Lista conversaciones | Cliente (TanStack Query) | `refetchInterval: 5000` mientras la tab está activa + `refetchOnWindowFocus` |
| Detalle conversación | Cliente | `refetchInterval: 3000` (mensajes nuevos) |
| Queue escalaciones | Cliente | `refetchInterval: 5000` |
| Settings | RSC con fetch directo | — |

**Optimistic updates** en `reply`, `escalate`, `close`, `claim`, `resolve`. Rollback si el server responde error.

**Errores del API** vienen como `{"error": code, "detail": msg}`. Un interceptor en `apiClient` los normaliza a una `ApiError` clase que el hook de Query expone vía `error`.

---

## 8. Páginas del dashboard interno

| # | Ruta | Endpoints | Notas |
|---|---|---|---|
| 1 | `/login` | (Supabase Auth) | Email + password. Redirect a `/dashboard` post-login. |
| 2 | `/dashboard` | `GET /admin/tenants` (nuevo) | Lista de tenants accesibles. Selector → `/dashboard/tenants/{id}/conversations`. |
| 3 | `/dashboard/tenants/[tenantId]/conversations` | `GET /conversations?status=&limit=&offset=` | Filtro por status, paginación, click → detalle. |
| 4 | `/dashboard/tenants/[tenantId]/conversations/[id]` | `GET /conversations/{id}`, `POST /reply`, `POST /escalate`, `POST /close` | Hilo + composer. Botones secundarios: escalar, cerrar. |
| 5 | `/dashboard/tenants/[tenantId]/escalations` | `GET /escalations`, `POST /claim`, `POST /resolve` | Queue de escalaciones pendientes; claim asigna al user logueado. |
| 6 | `/dashboard/tenants/[tenantId]/settings` | `GET /tenants/me/config` (con `X-Tenant-Id`) | Read-only: model, threshold, channels, branding. Editable en futuro sprint. |

---

## 9. Deuda nueva que destapa el frontend

Tres cosas hay que cablear en `apps/api` durante este sprint:

| Pendiente | Bloquea | Sub-PR | Estimado |
|---|---|---|---|
| **CORS middleware en FastAPI** con allowlist `[NEXT_PUBLIC_APP_URL]` | Cualquier request del navegador | 3.7 | 15 min |
| **`GET /admin/tenants`** — super_admin lista tenants accesibles (paginado) | Tenant switcher (página 2 del flow) | 3.6 | 1-2 h con tests |
| **`super_admin` necesita poder llamar `GET /tenants/me/config` pasando `X-Tenant-Id`** (validar que ya funciona — el code-path existe) | Settings del tenant | verificar en 3.7 | confirmar |

---

## 10. Variables de entorno

```bash
# apps/web/.env.local
NEXT_PUBLIC_API_URL=http://localhost:8000                  # staging: https://platform-staging-fdb7.up.railway.app
NEXT_PUBLIC_SUPABASE_URL=https://<proyecto>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon_key>
```

No usamos `SUPABASE_SERVICE_ROLE_KEY` en el web — todas las operaciones admin pasan por el API con el JWT del super_admin.

---

## 11. Despliegue (Railway)

- App nueva: `platform-web-staging`.
- Build context: repo root (Next.js + workspaces). Probablemente con `Dockerfile.web` o con buildpack Nixpacks; lo decidimos al llegar al sub-PR 3.7.
- Build cmd: `pnpm install --frozen-lockfile && pnpm --filter @auyan/web build`.
- Start cmd: `pnpm --filter @auyan/web start --port ${PORT}`.
- Healthcheck: `GET /api/health` (Route Handler trivial).

---

## 12. Plan por sub-PRs

| # | Branch | Entregable | Endpoints API tocados |
|---|---|---|---|
| **3.1** | `feat/sprint3-monorepo-scaffold` | pnpm workspaces, `packages/shared` vacío, scaffold `apps/web` con Next.js + Tailwind + shadcn + Biome + middleware auth + página `/login` funcional contra Supabase + redirect post-login | — |
| **3.2** | `feat/sprint3-api-client` | `openapi-typescript` integrado, `lib/api/client.ts`, TanStack Query provider, `GET /tenants/me` como smoke test renderizando datos reales | `GET /tenants/me` |
| **3.3** | `feat/sprint3-conversation-list` | Lista de conversaciones con filtros (status) y paginación; polling 5s | `GET /conversations` |
| **3.4** | `feat/sprint3-conversation-detail` | Detalle + composer + reply/escalate/close con optimistic updates | `GET /conversations/{id}`, `POST .../reply|escalate|close` |
| **3.5** | `feat/sprint3-escalations` | Queue + claim/resolve | `GET /escalations`, `POST .../claim|resolve` |
| **3.6** | `feat/sprint3-admin-tenants` | Endpoint `GET /admin/tenants` (API) + tenant switcher (web) + ruteo dinámico `/dashboard/tenants/[tenantId]/*` | `GET /admin/tenants` (nuevo) |
| **3.7** | `feat/sprint3-deploy` | CORS en API + deploy `apps/web` a Railway staging + smoke e2e Playwright (login → ver inbox → responder) | — |

Cada sub-PR contra `develop`, merge antes de arrancar el siguiente. Después del 3.7 cerramos Sprint 3 y abrimos Sprint 4 con `/clients/*` + deuda RLS + Realtime.

---

## 13. Lo que NO está en scope (recordatorio explícito)

- `/clients/*` (Sprint 4)
- Supabase Realtime (Sprint 4)
- Editar config del tenant desde el dashboard (Sprint 5+)
- Branding personalizado por tenant en el sidebar (Sprint 5+)
- i18n — todo en español, un solo locale
- Filtros avanzados (search, fecha, asignado)
- Notificaciones push o desktop
- Métricas y analytics (volumen de tickets, tiempo de respuesta, costo por tenant)
