# Auyan — Reglas del proyecto

## Contexto
Auyan es un BPO AI-native para CX support, verticalizando primero en ecommerce.
Modelo: AI + agentes humanos como servicio fully managed.
Evolución futura: SaaS estilo Crescendo.ai donde el cliente gestiona su propio agente.
No vocees, habla acento caraqueño venezolano, tuteame.

## Stack
- Backend: FastAPI (Python)
- Frontend: Next.js con TypeScript
- Base de datos: Supabase (Postgres + pgvector)
- Agente: LangGraph + Codex API (Codex-sonnet-4-6)
- Observabilidad: Langfuse
- Inbox operativo: Chatwoot
- Email inbound: Postmark
- Deploy: Railway

## Estructura del monorepo
- apps/api → FastAPI, agentes LangGraph, webhooks
- apps/web → Dashboard interno + dashboard cliente (Next.js)
- apps/widget → Chat embebible JS para clientes sin herramienta propia
- packages/shared → Tipos y utilidades compartidas entre apps
- docs → Documentación técnica

## Arquitectura crítica — multi-tenant
- TODAS las tablas de Supabase tienen tenant_id como columna obligatoria
- Nunca mezclar datos entre tenants bajo ninguna circunstancia
- Cada tenant tiene su propia knowledge base, configuración y prompts
- Row Level Security (RLS) activado en Supabase para todas las tablas

## Reglas de base de datos
- Soft delete siempre: columna deleted_at, nunca DELETE real
- Timestamps en todas las tablas: created_at y updated_at
- Migraciones versionadas, nunca modificar tablas directamente en producción

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
- Ramas automáticas de Codex: Codex/* (las crea el worktree, válidas tal cual; el PR igual va contra develop)
- Nunca commitear directo a main ni develop
- Formato de commits: feat:, fix:, chore:, docs:

## Observabilidad — lo más importante
- Todo lo que hace el agente se loguea en Langfuse sin excepción
- Cada decisión de escalar lleva razón explícita registrada
- Cada conversación tiene trace completo: qué pensó, qué tool llamó, por qué decidió
- Errores se capturan, loguean y alertan — nunca se silencian
- Tracking de tokens y costo por conversación y por tenant

## Flujo del agente
1. Ticket entra por cualquier canal
2. Se identifica el tenant
3. El agente recupera contexto (historial + knowledge base del tenant)
4. El agente decide: resolver o escalar
5. Si resuelve: responde vía API del canal correspondiente
6. Si escala: asigna a agente humano con contexto completo y razón del escalado
7. Todo queda registrado en Langfuse y en Supabase

## Integraciones previstas
- Chatwoot: inbox operativo interno para agentes humanos
- Zendesk: webhook receiver + API bidireccional
- Intercom: webhook receiver + API bidireccional
- Shopify: ver pedidos, cancelaciones, devoluciones
- WhatsApp: vía Twilio o 360dialog
- Instagram: vía Meta API
- Postmark: email inbound

## Selección de modelo

- Al inicio de cada sesión, recomendar qué modelo usar según la tarea descrita antes de arrancar.
- Si el usuario no especifica la tarea al inicio, preguntar qué va a hacer antes de arrancar.
- **Sonnet** (`Codex-sonnet-4-6`): tareas rutinarias de código, scaffolding, fixes, boilerplate y preguntas de contexto.
- **Opus** (`Codex-opus-4-7`): diseño de arquitectura, decisiones complejas del grafo de LangGraph, revisión de seguridad y RLS, y cuando Sonnet falle repetidamente en algo.

## Lo que nunca hay que hacer
- Modificar datos de un tenant desde el contexto de otro
- Responder al cliente final sin pasar por el grafo de LangGraph
- Deployar directo a producción sin pasar por staging
- Commitear .env, API keys o datos de clientes reales

## Organización de archivos por carpeta

### apps/api
- main.py → entrada de la aplicación FastAPI
- routers/ → endpoints organizados por dominio (tickets, tenants, webhooks)
- agents/ → grafos de LangGraph y lógica del agente
- agents/graph.py → grafo principal
- agents/nodes/ → cada nodo del grafo en su propio archivo
- agents/prompts/ → prompts versionados por tenant
- integrations/ → conectores externos (Zendesk, Chatwoot, Shopify, etc.)
- integrations/zendesk.py
- integrations/chatwoot.py
- integrations/shopify.py
- services/ → lógica de negocio reutilizable
- services/tickets.py
- services/tenants.py
- services/escalation.py
- db/ → modelos y queries de Supabase
- db/models.py
- db/queries.py
- core/ → configuración, constantes, utilidades
- core/config.py → variables de entorno
- core/security.py
- tests/ → tests organizados igual que el código

### apps/web
- app/ → páginas Next.js (App Router)
- app/dashboard/ → vista interna para agentes humanos
- app/clients/ → dashboard por tenant (vista del cliente)
- app/auth/ → login y autenticación
- components/ → componentes reutilizables
- lib/ → utilidades y llamadas a API

### apps/widget
- src/widget.ts → el chat embebible
- src/api.ts → conexión con apps/api
- dist/ → build final que se embebe en la web del cliente

### packages/shared
- types/ → interfaces y tipos compartidos entre apps
- utils/ → funciones utilitarias comunes

### docs
- architecture.md → decisiones de arquitectura
- onboarding.md → cómo incorporar un cliente nuevo
- runbooks/ → cómo resolver problemas comunes en producción

### Raíz del proeyecto
- AGENTS.md → este archivo
- .env.example → template de variables de entorno sin valores reales
- .gitignore → archivos que nunca se suben a GitHub
- docker-compose.yml → para levantar servicios localmente

por ultimo, estas no son normals grabadas para siempre, si tienes alguna sugerencia puedes sugerir cambios que yo tendre qeu aprobar antes de continuarlos y luego actualizar este archivo