# Arquitectura — Web app operativa (`apps/web`)

_Documento actualizado post-pivot el 2026-05-28. La visión general está en [`docs/architecture-overview.md`](architecture-overview.md); el estado operativo manda en [`docs/progress.md`](progress.md). Este archivo describe la arquitectura real de `apps/web` después del pivot BPO → Managed AI Service._

---

## 1. Contexto y objetivo

`apps/web` es la aplicación operativa de Auyan. Sirve dos experiencias en la misma app:

1. **Dashboard interno** (`/(dashboard)`) para Kenny, esposa y futuros roles internos (`super_admin`, `aide`, `qa_km`, `ops_manager`, `cs_manager`). Aquí se operan tenants, simulaciones, AOPs, aprobaciones, propuestas y playbook.
2. **Dashboard cliente** (`/clients/[tenantId]`) para `tenant_admin`. Aquí el cliente ve estado, conversaciones/escalaciones expuestas, datos factuales (`tenant_facts`) y, durante Bloque 1, onboarding, KB y reportes.

Post-pivot, Auyan **no hostea un BPO humano**. El cliente conserva su equipo CX. Auyan opera como Managed AI Service: configura, prueba, mantiene y mejora el agente IA, y empuja escalados al helpdesk del cliente cuando corresponde.

**Fuera de scope de `apps/web`:**

- Landing pública (`apps/landing`, Bloque 1.8).
- Chat widget propio. Auyan hereda canales del helpdesk del cliente.
- Canales directos WhatsApp/Instagram. Van vía Gorgias/Zendesk/Chatwoot.
- Supabase Realtime como requisito del MVP. El patrón actual sigue siendo polling con TanStack Query.

---

## 2. Decisiones tomadas

| Decisión | Elegido | Alternativas descartadas | Razón |
|---|---|---|---|
| Alcance actual | `/(dashboard)` interno + `/clients/[tenantId]` cliente | Apps separadas por rol | Una sola app reduce duplicación; layouts separados mantienen claridad |
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
| Despliegue | Vercel (desde s77) | Railway (usado hasta s76), Fly.io | Next.js nativo, plan Hobby gratis para staging |

---

## 3. Stack consolidado

```
Next.js 15  +  TypeScript strict  +  Tailwind v4  +  shadcn/ui
@supabase/ssr  +  TanStack Query v5  +  openapi-fetch  +  openapi-typescript
react-hook-form + zod  |  Vitest + Playwright  |  Biome
pnpm workspaces  |  Vercel
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
- `super_admin` accede al dashboard interno y puede operar tenants vía `X-Tenant-Id`.
- `tenant_admin` accede al dashboard cliente bajo `/clients/[tenantId]`.
- El rol `tenant_agent` fue removido en Bloque 0.1. No debe aparecer en rutas, permisos ni documentación nueva.
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
│   └── web/
│       ├── app/
│       │   ├── (auth)/
│       │   │   ├── login/page.tsx
│       │   │   └── layout.tsx
│       │   ├── (dashboard)/                       # dashboard interno
│       │   │   ├── layout.tsx                     # shell Mercury light + sidebar + topbar
│       │   │   ├── page.tsx                       # home cross-tenant
│       │   │   └── tenants/[tenantId]/
│       │   │       ├── conversations/
│       │   │       │   ├── page.tsx
│       │   │       │   └── [id]/page.tsx
│       │   │       ├── escalations/page.tsx
│       │   │       ├── approvals/page.tsx
│       │   │       ├── aops/page.tsx
│       │   │       ├── proposals/page.tsx
│       │   │       ├── simulator/page.tsx
│       │   │       └── playbook/page.tsx
│       │   ├── clients/[tenantId]/                 # dashboard cliente
│       │   │   ├── layout.tsx
│       │   │   ├── overview/page.tsx
│       │   │   ├── conversations/page.tsx
│       │   │   ├── conversations/[id]/page.tsx
│       │   │   ├── escalations/page.tsx
│       │   │   └── facts/page.tsx
│       │   ├── layout.tsx                         # root: providers (Query, Theme)
│       │   └── globals.css
│       ├── components/
│       │   ├── ui/                                # shadcn primitives
│       │   ├── clients/
│       │   ├── nav/
│       │   ├── proposals/
│       │   ├── simulator/
│       │   └── tenant-context/
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

**Regla operativa:** cualquier PR que modifique schemas/respuestas del API corre `pnpm gen:api-types` y comitea el diff. La verificación de drift debe quedar en CI antes de producción.

---

## 7. Data fetching y polling

| Vista | Pattern | Refetch |
|---|---|---|
| Login | client-only, sin Query | — |
| Layout `/(dashboard)` | RSC shell + cliente para tenant switcher/topbar | — |
| Layout `/clients/[tenantId]` | RSC shell cliente + client hooks por sección | — |
| Overview interno (`/(dashboard)`) | Cliente (TanStack Query) | manual |
| Lista conversaciones | Cliente (TanStack Query) | `refetchInterval: 5000` mientras la tab está activa + `refetchOnWindowFocus` |
| Detalle conversación | Cliente | `refetchInterval: 3000` |
| Escalaciones/aprobaciones/propuestas | Cliente | `refetchInterval: 5000` donde hay colas activas |
| Simulator | Cliente | polling en batches/runs activos |
| Playbook/facts | Cliente con mutations | invalidación post-save |

**Optimistic updates** en `reply`, `escalate`, `close`, `claim`, `resolve`. Rollback si el server responde error.

**Errores del API** vienen como `{"error": code, "detail": msg}`. Un interceptor en `apiClient` los normaliza a una `ApiError` clase que el hook de Query expone vía `error`.

---

## 8. Páginas actuales

| # | Ruta | Endpoints | Notas |
|---|---|---|---|
| 1 | `/login` | (Supabase Auth) | Email + password. Redirect a `/dashboard` post-login. |
| 2 | `/dashboard` | `GET /admin/tenants`, métricas agregadas | Home interno cross-tenant. Bloque 1.7 lo convertirá en Review Queue real. |
| 3 | `/dashboard/tenants/[tenantId]/conversations` | `GET /conversations` | Debug operativo de conversaciones del tenant. |
| 4 | `/dashboard/tenants/[tenantId]/conversations/[id]` | `GET /conversations/{id}` + acciones | Hilo, reasoning y acciones operativas. |
| 5 | `/dashboard/tenants/[tenantId]/escalations` | `GET /escalations` + acciones | Escalaciones visibles para operación interna. |
| 6 | `/dashboard/tenants/[tenantId]/approvals` | pending approvals | Cola L3 / human approval. |
| 7 | `/dashboard/tenants/[tenantId]/aops` | AOP endpoints | Editor operativo de AOPs. |
| 8 | `/dashboard/tenants/[tenantId]/proposals` | proposals endpoints | Slow agent proposals. |
| 9 | `/dashboard/tenants/[tenantId]/simulator` | `/simulations/*` | Scenarios, runs y judge detail. |
| 10 | `/dashboard/tenants/[tenantId]/playbook` | `GET/PUT /tenants/me/playbook` | Biblia operativa del cliente, editable por Auyan. |
| 11 | `/clients/[tenantId]/overview` | métricas cliente | Dashboard cliente MVP existente. Bloque 1.6 lo amplía a 7 secciones. |
| 12 | `/clients/[tenantId]/conversations` | `GET /conversations` | Vista cliente de conversaciones. |
| 13 | `/clients/[tenantId]/escalations` | `GET /escalations` | Vista cliente de escalaciones. |
| 14 | `/clients/[tenantId]/facts` | `GET/PUT /tenants/me/facts` | Datos factuales editables por el cliente. |

---

## 9. Estado actual y deuda

| Pendiente | Bloquea | Bloque | Nota |
|---|---|---|---|
| Agent Verification Staging | Confianza operativa antes de vender/activar clientes reales | 0.11 | Foco activo según `progress.md`: LangSmith, simulator costeado, Shopify test store real y Chatwoot primero. Cambios principalmente en API/scripts; web solo consume resultados existentes. |
| Completar onboarding wizard + lifecycle | Flujo cliente end-to-end | 1.3 | ✅ Completo. |
| KB drop-zone + cola pending review | Onboarding útil con documentos reales | 1.4 | ✅ Completo con curación Auyan. |
| Reportes semanales | Propuesta managed visible al cliente | 1.5 | ✅ Completo: email resumen + dashboard como fuente completa. |
| Dashboard cliente 7 secciones | Demo comercial completa | 1.6 | ✅ Completo: Home, Insights, Reportes, KB, Aprobaciones, Onboarding, Configuración. |
| Review Queue interna por rol | Operación escalable | 1.7 | ✅ Completo: Home interno cross-tenant con filtros por foco de rol. |

---

## 10. Variables de entorno

```bash
# apps/web/.env.local
NEXT_PUBLIC_API_URL=http://localhost:8000                  # staging: https://auyan-api-staging-350779301730.europe-west3.run.app
NEXT_PUBLIC_SUPABASE_URL=https://<proyecto>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon_key>
```

No usamos `SUPABASE_SERVICE_ROLE_KEY` en el web — todas las operaciones admin pasan por el API con el JWT del super_admin.

---

## 11. Despliegue (Vercel)

- Proyecto staging: `auyan-web-staging` (equipo `kenny-medinas-projects`) → `https://auyan-web-staging.vercel.app`.
- Root Directory: `apps/web`; install `pnpm install --frozen-lockfile`, build `pnpm build`.
- `.vercelignore` en la raíz: sube solo `apps/web` + `packages/shared` + manifiestos (nunca `.env*`, API, docs ni migraciones; patrones anclados con `/`).
- Env vars (Production y Preview): `NEXT_PUBLIC_API_URL` (Cloud Run), `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` (pública por diseño; marcada `--type config`).
- Deploy automático: `.github/workflows/deploy-web-staging.yml` corre `vercel deploy --prod` con cada push a `develop` que toque `apps/web`, `packages/shared` o los manifiestos del workspace (también a mano con *Run workflow*). Vercel Hobby no conecta repos privados de una organización de GitHub, por eso va por CLI y no por la integración Git. Secretos del repo: `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`.
- Deploy manual (fallback): `vercel deploy --prod --yes` desde la raíz (repo enlazado con `vercel link`; `.vercel/` ignorado por git).
- El API debe incluir la URL de Vercel en `ALLOWED_ORIGINS` (CORS) y Supabase Auth debe tenerla como Site URL / Redirect URL (magic links).

---

## 12. Plan vigente por sub-PRs

El plan Sprint 3 original queda histórico. El estado operativo vigente lo manda `progress.md`.

| Sub-PR | Estado | Entregable |
|---|---|---|
| 0.11A | activo | Agent Verification Staging: LangSmith como observabilidad primaria, simulator optimizado por coste, Shopify real y Chatwoot primero. |
| 1.0 | ✅ completo | Design Sprint: `DESIGN.md`, tokens, primitives, refactor shell Mercury light. |
| 1.1 | ✅ completo | `tenant_playbook` table + queries + UI super_admin editor. |
| 1.2 | ✅ completo | `tenant_facts` table + form cliente + lectura del agente como contexto estructurado. |
| 1.3 | ✅ completo | Onboarding guiado por invitación (9 pasos) + `agent_lifecycle_state` + comunicaciones email. |
| 1.4 | ✅ completo | KB drop-zone + cola pending review + UI super_admin procesamiento. |
| 1.5 | ✅ completo | Reporte semanal automatizado: `weekly_reports` + cron lunes + UI aprobación + Postmark. |
| 1.6 | ✅ completo | Dashboard cliente 7 secciones MVP con data viz. |
| 1.7 | ✅ completo | Dashboard super_admin Home/Review Queue + filtros por rol. |
| 1.8 | ✅ completo | `apps/landing` + Aceternity UI-style + páginas públicas + Plausible. |
| 1.9 | ✅ completo | Email outbound general: templates editables + queue + retry logic + consola interna. |
| 1.10 | ⏭️ operativo | Facturación manual (fuera del producto) para los primeros clientes; Stripe queda para Bloque 2. |

---

## 13. Lo que NO está en scope de `apps/web` actual

- Landing pública. Va en `apps/landing`.
- Construir canales directos. Se heredan del helpdesk del cliente.
- BPO interno con agentes de Auyan respondiendo tickets. Ya fue descartado.
- Reintroducir `tenant_agent`. El rol fue eliminado.
- Supabase Realtime como dependencia de Bloque 1.
- Branding profundo por tenant en el sidebar.
- i18n — todo en español, un solo locale
- Filtros avanzados fuera de las colas donde aportan valor real.
- Notificaciones push o desktop
