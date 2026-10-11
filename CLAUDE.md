# Auyan — Reglas del proyecto

## Contexto
Auyan opera el agente IA de CX de cada cliente (e-commerce). Restricción técnica que se deriva de eso:
- El cliente no configura el agente: no hay signup público ni self-serve. Los tenants los crea `super_admin` y el cliente entra por invitación (magic link).
- Prompts, AOPs, RAG y activación los gestiona el equipo interno; el cliente solo aporta KB, edita `tenant_facts` y aprueba acciones L3.
- Los escalados van al equipo de soporte del propio cliente, vía su helpdesk.
No vocees, habla acento caraqueño venezolano, tuteame.

## Stack
- Backend: FastAPI (Python 3.12)
- Frontend: Next.js 15 + TypeScript + Tailwind v4 + shadcn
- Base de datos: Supabase (Postgres + pgvector + Auth + RLS)
- Agente: LangGraph + Claude API (Sonnet 4.6 default y judge de simulator, Haiku 4.5 para intent classifier/simulator, Opus 4.7 para L3/supervisor financiero y judge/calibración explícita)
- Embeddings: OpenAI text-embedding-3-small
- Observabilidad: LangSmith como fuente primaria de staging/evals; Langfuse queda como espejo secundario existente mientras siga conectado
- Helpdesks del cliente: Chatwoot Cloud / Gorgias / Zendesk / Intercom reactivo
- Email saliente (Auyan→cliente): Postmark
- Deploy: API en Google Cloud Run (proyecto `auyan-510116`, `europe-west3`; `apps/api/scripts/deploy_cloud_run.sh`) + dashboard en Vercel (`apps/web`). Railway se abandonó en la sesión 77

## Estructura del monorepo
- apps/api → FastAPI, agentes LangGraph, webhooks
- apps/web → Dashboard super_admin + dashboard cliente (Next.js)
- apps/landing → Landing pública (Next.js)
- packages/shared → Tipos y utilidades compartidas entre apps
- docs → Documentación técnica

## Arquitectura crítica — multi-tenant
- TODAS las tablas de Supabase tienen tenant_id como columna obligatoria
- Nunca mezclar datos entre tenants bajo ninguna circunstancia
- Cada tenant tiene su propia knowledge base (RAG), AOPs, configuración y credentials de integración
- Row Level Security (RLS) activado en Supabase para todas las tablas

## Reglas de base de datos
- Soft delete siempre: columna deleted_at, nunca DELETE real
- Timestamps en todas las tablas: created_at y updated_at
- Migraciones versionadas en supabase/migrations/, nunca modificar tablas directamente en producción
- El deploy (Cloud Run / Vercel) NO aplica SQL. Las migraciones se corren manualmente vía psql o Supabase SQL Editor

## Reglas de código
- Nunca hardcodear API keys ni secrets en el código
- Variables sensibles siempre en .env (nunca se commitea)
- Type hints en todo el código Python
- Manejo explícito de errores, nunca silenciar excepciones
- Toda función nueva lleva su test básico

## Ramas y commits
- main → producción, solo recibe merges desde develop, siempre por PR
- develop → staging, aquí se integran todos los cambios
- Ramas de trabajo: feature/nombre, fix/nombre, chore/nombre, docs/nombre
- Ramas automáticas de Claude Code: claude/* (las crea el worktree, válidas tal cual; el PR igual va contra develop)
- Nunca commitear directo a main
- Todo cambio va por rama + PR contra develop (así corre el CI), salvo la excepción de abajo
- Excepción: commit directo a develop solo si el commit toca únicamente `docs/**` (p. ej. el cierre de sesión en progress.md). Si mezcla docs con cualquier otra ruta, va por PR
- Formato de commits: feat:, fix:, chore:, docs:
- El cuerpo del PR lleva `Closes #N` por cada issue que resuelve (el workflow `close-issues-on-develop` los cierra al mergear en develop, porque GitHub solo autocierra al mergear en main); `Refs #N` si el issue sigue abierto

## Observabilidad — lo más importante
- LangSmith es la fuente primaria de observabilidad en staging/evals
- Langfuse ya no es la fuente de verdad operativa; si sigue conectado, funciona como espejo secundario
- Todo lo que hace el agente debe quedar traceado en LangSmith sin excepción
- Cada decisión de escalar lleva razón explícita registrada
- Cada conversación tiene trace completo: qué pensó, qué nodo del grafo corrió, qué skill/tool llamó, por qué decidió, coste y errores
- Cada run visible en LangSmith debe correlacionar con Supabase (conversación, audit log y/o run correspondiente)
- Errores se capturan, loguean y alertan — nunca se silencian
- Tracking de tokens y costo por conversación y por tenant

## Flujo del agente
1. Ticket entra al helpdesk del cliente → webhook a Auyan
2. Se identifica el tenant
3. El agente recupera contexto (historial + knowledge base del tenant)
4. El nodo select_aop clasifica el intent y activa el AOP correspondiente
5. El agente ejecuta el loop ReAct: reason → (execute_skill si aplica) → respond o escalate
6. Si resuelve: responde vía el adapter del helpdesk del cliente
7. Si escala: push al helpdesk del cliente con contexto completo y razón del escalado (el equipo CX del cliente atiende)
8. Todo queda registrado en LangSmith y en Supabase; Langfuse solo como espejo secundario si está activo

## Roles del sistema
- `super_admin` — acceso total cross-tenant (Kenny + esposa)
- `tenant_admin` — acceso scoped al tenant del cliente
- Del lado cliente, `tenant_admin` es el único rol

## Integraciones
- Chatwoot Cloud: helpdesk con API key, bidireccional
- Gorgias: helpdesk importante para Shopify, OAuth, bidireccional
- Zendesk: helpdesk alternativo, OAuth, bidireccional
- Intercom: reactivo (si cliente lo pide)
- Shopify: 11 skills implementadas — 5 L1 (lectura), 2 L2 (escritura reversible), 4 L3 (destructivas con approval)
- Postmark: email saliente Auyan→cliente (reports, notificaciones)
- WhatsApp vía Zernio: canal de mensajería, NO helpdesk (ADR 0010). Los escalados van por handoff al helpdesk del cliente. La key maestra de Zernio solo vive en scripts de operación (`.env.zernio` local), nunca en el runtime ni en `.env.staging`

## Lo que nunca hay que hacer
- Modificar datos de un tenant desde el contexto de otro
- Responder al cliente final sin pasar por el grafo de LangGraph + AOP selector
- Deployar directo a producción sin pasar por staging
- Commitear .env, API keys o datos de clientes reales

## Organización de archivos por carpeta

### apps/api
- main.py → entrada de la aplicación FastAPI
- routers/ → endpoints organizados por dominio (webhooks, tenants, conversations, escalations, aops, approvals, proposals, reasoning, tool_permissions)
- agents/ → grafo LangGraph y lógica del agente
  - agents/graph.py → grafo principal (11 nodos + loop ReAct)
  - agents/nodes/ → cada nodo en su propio archivo
  - agents/state.py → AgentState completo
  - agents/dependencies.py → AgentDependencies (ReasoningTracker, AuditLogger)
- aops/ → AOP compiler + TTL cache + Postgres NOTIFY listener
- skills/ → Skills framework (base, registry) + skills por proveedor
  - skills/shopify/ → 11 skills (5 L1 + 2 L2 + 4 L3)
- slow_agent/ → LLM-as-judge batch (transcript, judge, runner, sampling)
- evals/ → harness de eval + fixtures YAML por AOP
- integrations/ → clientes HTTP externos (shopify.py, langsmith_client.py, anthropic_client.py, helpdesks, postmark.py; langfuse_client.py mientras exista como espejo)
- services/ → lógica de negocio reutilizable (tenants, conversations, escalations, cleanup, reasoning, audit, pii, rate_limit)
- db/ → modelos Pydantic + queries asyncpg
- core/ → config (pydantic-settings), security (JWT ES256), errors (DomainError)
- scripts/ → utilidades operativas (seed_kb, send_test_webhook, activate_shopify, run_slow_agent)
- tests/ → tests organizados igual que el código

### apps/web
- app/ → páginas Next.js (App Router)
  - app/(dashboard)/ → dashboard operativo super_admin
  - app/clients/ → dashboard read/write para tenant_admin
  - app/(auth)/ → login y autenticación
- components/ → componentes reutilizables (inbox, reasoning, aops, proposals, approvals)
- lib/ → utilidades, hooks TanStack Query, cliente openapi-fetch tipado

### packages/shared
- src/ → tipos compartidos entre apps (api-types.ts, enums.ts)

### docs — convención documental (tres niveles)

1. **Norte** (se leen siempre al arrancar): `CLAUDE.md` + `docs/progress.md`. Regla dura de
   progress: máximo **3 cabeceras de sesión** — al cerrar cada sesión, la más vieja se mueve a
   `progress-archive.md` en el mismo commit que actualiza progress.
2. **Vivos** (se leen cuando el tema aplica): `architecture-overview.md` (punto de entrada
   técnico: stack, roles, onboarding, roadmap), `architecture-agent-v2.md` (mapa técnico del
   agente; en el detalle manda el código + tests), `architecture-web.md`, `DESIGN.md`,
   `billing-engine.md`, `onboarding-system-plan.md`, y `docs/adr/` (decisiones de arquitectura
   en formato Nygard — nuevas decisiones estructurales añaden su ADR).
3. **Históricos** (`docs/archive/` + `docs/progress-archive.md`): **NUNCA son fuente de verdad ni
   instrucciones vigentes** — ni para humanos ni para agentes. Cuando un diseño se implementa y
   verifica, su doc se archiva con banner de histórico y la verdad pasa al código + tests.

El repo solo contiene documentación técnica: nada de negocio, ventas ni GTM.

### Raíz del proyecto
- CLAUDE.md → este archivo
- .env.example → template de variables de entorno sin valores reales
- .gitignore → archivos que nunca se suben a GitHub
- supabase/migrations/ → todas las migraciones SQL versionadas

por último, estas no son normas grabadas para siempre, si tienes alguna sugerencia puedes sugerir cambios que yo tendrás que aprobar antes de continuarlos y luego actualizar este archivo

## Issue tracker

Los issues y PRDs viven como GitHub Issues en `Auyan-ai/platform` (CLI `gh`).

Cola de trabajo de agentes: `agent-queue` (concreto, un agente puede tomarlo) y `needs-human` (requiere una decisión humana). `wontfix` para descartados.
