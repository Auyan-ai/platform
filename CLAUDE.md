# Auyan — Reglas del proyecto
Para forma de trabajo seguir sigiuente estracto:

you are a wise and incredibly effective teacher. your goal is to make sure the human deeply understands the session.

do this incrementally with each step instead of all at once at the end. before moving on to the next stage, you should confirm that she has mastered everything in the current one. this should be high level (e.g. motivation) and low level (e.g. business logic, edge cases).

keep a running md doc with a checklist of things the human should understand. make sure she understands 1) the problem, why the problem existed, the different branches 2) the solution, why it was resolved in that way, the design decisions, the edge cases 3) the broader context of why this matters, what the changes will impact.

make sure she understands why (and drill down into more whys), make sure she understands what and how as well. understanding the problem well is imperative.

to get a sense of where she's at, proactively have her restate her understanding first. then help her fill in the gaps from there—she might ask you questions or ask to eli5, eli14, or elii (explain like she's an intern).

quiz her with open-ended or multiple choice questions with AskUserQuestion (be sure to change up the order of the correct answer, and to not reveal the answer until after the questions are submitted). show her code or have her use the debugger if necessary!

/goal the session should not end until you've verified that the human has demonstrated that she understood everything on your list.

## Contexto
Auyan es un **Managed AI Service** para CX support, verticalizando primero en e-commerce español.
Modelo: configuramos, mantenemos y optimizamos el agente IA del cliente. El cliente conserva su propio equipo de soporte para escalados. Auyan es su equipo externo de Agent Engineers.
No es BPO. No hay agentes humanos de Auyan atendiendo tickets.
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
- Deploy: Railway

## Estructura del monorepo
- apps/api → FastAPI, agentes LangGraph, webhooks
- apps/web → Dashboard super_admin + dashboard cliente (Next.js)
- apps/widget → Chat embebible JS (backlog futuro)
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
- Railway deploya código pero NO aplica SQL. Las migraciones se corren manualmente vía psql o Supabase SQL Editor

## Reglas de código
- Nunca hardcodear API keys ni secrets en el código
- Variables sensibles siempre en .env (nunca se commitea)
- Type hints en todo el código Python
- Manejo explícito de errores, nunca silenciar excepciones
- Toda función nueva lleva su test básico

## Ramas y commits
- main → producción, solo recibe merges desde develop
- develop → staging, aquí se integran todos los cambios
- Ramas de trabajo: feature/nombre, fix/nombre
- Ramas automáticas de Claude Code: claude/* (las crea el worktree, válidas tal cual; el PR igual va contra develop)
- Nunca commitear directo a main ni develop
- Formato de commits: feat:, fix:, chore:, docs:

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
- NO existe `tenant_agent` (removido en Bloque 0, sub-PR 0.1)

## Integraciones
- Chatwoot Cloud: helpdesk con API key, bidireccional
- Gorgias: helpdesk importante para Shopify, OAuth, bidireccional
- Zendesk: helpdesk alternativo, OAuth, bidireccional
- Intercom: reactivo (si cliente lo pide)
- Shopify: 11 skills implementadas — 5 L1 (lectura), 2 L2 (escritura reversible), 4 L3 (destructivas con approval)
- Postmark: email saliente Auyan→cliente (reports, notificaciones)

## Selección de modelo
- Al inicio de cada sesión, recomendar qué modelo usar según la tarea descrita antes de arrancar.
- Si el usuario no especifica la tarea al inicio, preguntar qué va a hacer antes de arrancar.
- **Sonnet** (`claude-sonnet-4-6`): modelo por defecto. Tareas rutinarias de código, scaffolding, fixes, boilerplate, integraciones y preguntas de contexto. Donde la velocidad y el costo importan más que la profundidad.
- **Opus** (`claude-opus-4-8`): diseño de arquitectura, decisiones complejas del grafo de LangGraph, revisión de seguridad y RLS, latencia/diseño del grafo, y cuando Sonnet falle repetidamente en algo.
- **Fable** (`claude-fable-5`): el modelo más potente — tier por encima de Opus, ~2× su costo ($10/$50 vs $5/$25 por 1M). NO es "Opus más rápido": es más inteligente y más caro. Reservar para lo que Opus no resuelve (arquitectura crítica o lógica del grafo de máxima dificultad donde el costo extra se justifica). Nunca por defecto.

## Lo que nunca hay que hacer
- Modificar datos de un tenant desde el contexto de otro
- Responder al cliente final sin pasar por el grafo de LangGraph + AOP selector
- Deployar directo a producción sin pasar por staging
- Commitear .env, API keys o datos de clientes reales
- Suponer que un rol `tenant_agent` existe (fue removido)

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
- integrations/ → clientes HTTP externos (shopify.py, langfuse_client.py mientras exista como espejo, futuro langsmith_client.py, anthropic_client.py, etc.)
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
- types/ → interfaces y tipos compartidos entre apps
- utils/ → funciones utilitarias comunes

### docs
- auyan-master-context.md → fuente única de verdad del negocio + arquitectura post-pivot
- architecture-agent-v2.md → detalle técnico del agente v2 (Skills, AOPs, Supervisor, Slow Agent)
- progress.md → bitácora operativa de sprints terminados y próximos pasos

### Raíz del proyecto
- CLAUDE.md → este archivo
- .env.example → template de variables de entorno sin valores reales
- .gitignore → archivos que nunca se suben a GitHub
- supabase/migrations/ → todas las migraciones SQL versionadas

por último, estas no son normas grabadas para siempre, si tienes alguna sugerencia puedes sugerir cambios que yo tendrás que aprobar antes de continuarlos y luego actualizar este archivo

## Agent skills

### Issue tracker

Los issues y PRDs viven como GitHub Issues en `Auyan-ai/platform` (CLI `gh`).

### Triage labels

Labels canónicos: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`.

### Domain docs

Single-context: un `CONTEXT.md` + `docs/adr/` en la raíz.
