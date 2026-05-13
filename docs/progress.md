# Auyan — Estado del proyecto

_Última actualización: 2026-05-13_

---

## Sprint 0 — Fundación (completado)

**Objetivo:** Establecer las bases del proyecto antes de escribir una línea de código productivo.

### Completado
- [x] Repositorio creado en GitHub (`Auyan-ai/platform`)
- [x] Estructura de monorepo definida en CLAUDE.md (`apps/api`, `apps/web`, `apps/widget`, `packages/shared`, `docs`)
- [x] CLAUDE.md con reglas completas: multi-tenant, RLS, soft delete, observabilidad, flujo del agente, integraciones previstas, organización de archivos
- [x] `.gitignore` configurado (incluye `.DS_Store`, `.env`)
- [x] Flujo de ramas definido: `main` → producción, `develop` → staging, `feature/*` y `fix/*` para trabajo
- [x] Reglas de selección de modelo documentadas (Sonnet vs Opus según tarea)
- [x] Primer PR abierto y flujo de contribución validado ([PR #1](https://github.com/Auyan-ai/platform/pull/1))

### Estado del repo
El repositorio contiene únicamente documentación. Ninguna carpeta de código (`apps/`, `packages/`) existe todavía — todo está por construir.

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

## Sprint 1 — Core del sistema (siguiente)

**Objetivo:** Tener el sistema funcionando end-to-end con un solo tenant de prueba: ticket entra, agente responde, todo queda logueado.

### Backend (`apps/api`)
- [ ] Scaffolding inicial de FastAPI (`main.py`, estructura de carpetas)
- [ ] Configuración de variables de entorno (`core/config.py`)
- [x] Esquema de Supabase con multi-tenant y RLS (`supabase/migrations/20260513000000_initial_schema.sql`)
  - Tablas: `tenants`, `users` (staff), `end_customers`, `conversations`, `messages`, `escalations`, `knowledge_base_documents`, `knowledge_base_chunks` (pgvector 1536), `tenant_configurations`, `tenant_prompts` (versionados)
  - RLS por JWT claim `tenant_id` + rol `super_admin` para Auyan
  - FKs compuestas `(id, tenant_id)` para impedir cross-tenant
  - Soft delete (`deleted_at`) y `updated_at` automático en todas
- [ ] Modelos y queries base (`db/models.py`, `db/queries.py`)
- [ ] Grafo inicial de LangGraph (`agents/graph.py`)
  - Nodo: recuperar contexto del tenant
  - Nodo: generar respuesta
  - Nodo: decidir escalar o resolver
- [ ] Integración con Langfuse (trace completo por conversación)
- [ ] Webhook receiver básico (endpoint genérico de tickets)
- [ ] Tests básicos por módulo

### Infraestructura
- [ ] `docker-compose.yml` para levantar servicios localmente
- [ ] `.env.example` con todas las variables necesarias
- [ ] Deploy inicial en Railway (entorno staging)

### Criterio de done del Sprint 1
Un ticket enviado vía POST al endpoint de la API es procesado por el agente, genera una respuesta, y el trace completo aparece en Langfuse — todo bajo un `tenant_id` de prueba.

---

## Backlog (post Sprint 1)

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
