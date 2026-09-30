# Arquitectura — visión general

Punto de entrada técnico al sistema. El detalle del agente está en
[`architecture-agent-v2.md`](architecture-agent-v2.md), el del dashboard en
[`architecture-web.md`](architecture-web.md) y las decisiones en [`adr/`](adr/README.md).

**Restricción que moldea el producto:** Auyan opera el agente de cada cliente. No hay signup
público ni configuración self-serve: los tenants los crea `super_admin`, el cliente entra por
invitación (magic link) y solo edita lo que se lista en "KB — tres niveles". Prompts, AOPs,
RAG y activación del agente los gestiona el equipo interno.

---

## 1. Stack

| Capa | Tecnología |
|---|---|
| Backend | FastAPI (Python 3.12) — `apps/api` |
| Dashboard | Next.js 15 + TypeScript + Tailwind v4 + shadcn — `apps/web` |
| Landing | Next.js 15 + Framer Motion — `apps/landing` |
| Base de datos | Supabase (Postgres + pgvector + Auth + RLS) |
| Agente | LangGraph + Claude (Sonnet default, Haiku intent/simulator, Opus L3/calibración) |
| Embeddings | OpenAI text-embedding-3-small (1536 dims) |
| Observabilidad | LangSmith primario; Langfuse espejo secundario mientras siga conectado |
| Email saliente (Auyan→cliente) | Postmark |
| Helpdesk del cliente | Chatwoot, Gorgias, Zendesk; Intercom reactivo |
| Billing | Motor de medición propio ([`billing-engine.md`](billing-engine.md)); Stripe pendiente |
| Deploy | API en Google Cloud Run (`europe-west3`) + dashboard en Vercel (desde s77; antes Railway) |

### Dominios

- `auyan.com` — landing pública
- `app.auyan.com` — dashboard (cliente + super_admin con auth)
- `api.auyan.com` — backend FastAPI

### Lo que ya está construido

- Multi-tenancy con RLS + `tenant_scope` GUC
- Grafo LangGraph 11 nodos + ReAct loop
- Skills L1/L2/L3 con permission gate (11 Shopify)
- AOPs versionados con workspaces staging/production + eval gate 80%
- Supervisor Sonnet/Opus por tier
- Human approval L3 con cola UI
- Slow Agent con two-step judge (Sonnet→Opus si confidence <0.7)
- Agent Reasoning UI con PII masking
- Audit log con pseudonimización
- Rate limiting + budget gate por tenant
- Cleanup automático con timeouts por canal
- Simulator multi-turn + LLM-as-judge

---

## 2. Roles

**Tabla `internal_users`** con role enum: `super_admin`, `aide`, `qa_km`, `ops_manager`,
`cs_manager`; asignación por cliente en `tenant_assignments` (`assigned_aide_id`/`assigned_qa_id`).
Del lado cliente solo existe `tenant_admin` (`tenant_agent` fue eliminado).

| Rol | Qué puede hacer |
|---|---|
| `super_admin` | Acceso total cross-tenant |
| `aide` (AI Deployment Engineer) | AOPs, integraciones, KB de sus clientes asignados |
| `qa_km` (QA + Knowledge Management) | Drafts shadow, KB drops, `tenant_playbook`; transversal |
| `ops_manager` | Reportes semanales, schedule; sin edición técnica |
| `cs_manager` | Sin permisos técnicos |
| `tenant_admin` | Dashboard `/clients` de su tenant: KB (aporta), `tenant_facts`, aprobaciones L3, reportes |

---

## 3. Onboarding de un tenant

Detalle y decisiones en [`onboarding-system-plan.md`](onboarding-system-plan.md).

1. `super_admin` crea el tenant (`tenant_provisioning`) → se clona la plantilla starter
   (AOPs + esqueleto de playbook + schema de facts).
2. El cliente recibe magic link (Supabase invite) y completa el **onboarding guiado** de 9 pasos
   (`OnboardingWizard.tsx`): datos básicos, brand voice, `tenant_facts`, Shopify, helpdesk,
   drop-zone de KB, DPA/GDPR, call opcional con el AIDE, confirmación.
3. Lifecycle (`agent_lifecycle_state`): `initial→discovery→building` automático;
   `building→shadow→ramping→active` lo aprueba el AIDE.

---

## 4. Arquitectura del producto

### KB — tres niveles

| Nivel | Quién | Qué |
|---|---|---|
| 🔴 Nunca | Solo Auyan | Prompts, AOPs, contenido RAG, retrieval config |
| 🟡 Aporta no edita | Cliente → Auyan cura | Documentos, URLs, políticas (drop-zone → `tenant_knowledge_submissions`) |
| 🟢 Edita directo | Cliente, form plano | `tenant_facts`: horarios, teléfono, dirección, links — NO entra al RAG |

### Adapters por tenant

**Patrón**: `MessageProvider` (base) + `HelpdeskProvider` (extends).

```python
class MessageProvider(Protocol):
    async def parse_inbound_webhook(payload) -> InboundMessage
    async def send_outbound(ctx, conversation_ref, content, attachments) -> None

class HelpdeskProvider(MessageProvider, Protocol):
    async def add_internal_note(ctx, ticket_ref, content) -> None
    async def assign_to_human(ctx, ticket_ref, reason) -> None
    async def update_status(ctx, ticket_ref, status) -> None
    async def push_escalation(ctx, conversation, reason, agent_context) -> ExternalTicketRef
```

**Implementaciones**: `ZendeskAdapter`, `ChatwootAdapter`, `GorgiasAdapter` (helpdesk) +
`PostmarkEmailAdapter` (outbound Auyan→cliente).

**Tabla `tenant_integrations`** con `kind` + `provider` + `credentials_encrypted` + `config`.

### Escalación al equipo del cliente

- **Con helpdesk**: `push_escalation()` crea ticket o internal note con contexto completo + razón.
- **Sin helpdesk**: email a `notif_email` del tenant vía `PostmarkEmailAdapter`.
- Schema `escalations`: `external_ticket_ref` + `external_provider` + `notified_at` +
  `acknowledged_at` (no hay asignación a usuarios internos).

### Shadow mode

1. Ticket entra al helpdesk del cliente → webhook a Auyan
2. El agente genera un draft y lo postea como **internal note** (no se envía al cliente final)
3. El equipo del cliente responde manualmente; Auyan registra el diff draft vs respuesta real
4. Tras N tickets con alta concordancia por categoría → se propone activar esa categoría
5. Activación **por categoría**, con aprobación explícita del cliente

### Simulator / evals

- **3 tipos de test**: unit (eval harness), integration (skills + DB), simulation (multi-turn).
- **4 dimensiones del LLM-as-judge**: Reasoning (¿siguió el AOP?), Knowledge (¿sin alucinar?),
  Tools (¿skills e inputs correctos?), Brand voice (¿tono y guardrails?).
- **Tablas**: `user_profiles`, `simulation_scenarios`, `simulation_runs`.
- Código: `apps/api/simulator/` + `routers/simulations.py`.

### AOPs con `steps[]` opcional

Campo opcional `steps[]` en el schema de AOP + eventos `step_entered`/`step_completed`
(extiende `agent_reasoning_events`), para análisis de drop-off por step.

### Dashboard cliente (`/clients`)

1. **Home** — KPIs + heatmap + headline del reporte + lifecycle phase
2. **Insights** — explorer de conversaciones con filtros, intents y reasoning panel
3. **Reportes** — historial + actual con sección narrativa
4. **Knowledge Base** — drop-zone + `tenant_facts` + estado de procesamiento
5. **Aprobaciones** — cola L3 pending
6. **Onboarding** — solo durante fase inicial
7. **Configuración** — integraciones, branding, AIDE asignado

### Dashboard super_admin

- **Cross-tenant**: Home (review queue), Clientes, Reportes, Schedule, Adapters & Health
- **Scoped a tenant**: Overview, Lifecycle, Conversations (debug), KB Management, Approvals,
  AOPs Editor, Simulator, Proposals, Playbook
- **Home = Review Queue** filtrada por rol.

### Qué es editable en DB vs código

| Pieza | Decisión |
|---|---|
| Pasos del wizard onboarding | Código (PR + redeploy) |
| Preguntas cuestionario brand voice | DB editable |
| `tenant_facts` schema | DB editable por vertical |
| AOPs | DB con workspaces |
| Tool permissions | DB granular |
| Notification templates (emails) | DB editable |
| Report templates | DB editable + Jinja |
| Prompts del agente | Compilados desde AOPs |
| Adapter registry | Código |

### Privacidad y seguridad

| Área | Medida | Estado |
|---|---|---|
| Credentials integraciones | `credentials_encrypted` bytea con salt por tenant | ✅ |
| Uploads cliente | `tenant_knowledge_submissions` con texto/URL; PDFs/binarios + Storage pendientes | Parcial |
| PII en mensajes | SHA-256 + salt por tenant | ✅ |
| Cross-tenant access | Solo super_admin con MFA + audit log de accesos | Reforzar |
| Trazas de observabilidad | Staging traza datos test/autorizados en LangSmith; producción requiere redacción/retención formal antes de activar | Staging |
| GDPR DPA | Firma en onboarding paso 7 | ✅ |
| Right to erasure | Endpoint `DELETE /tenants/me/data` + cron purga 30d | Pendiente |
| Servidores | EU (Supabase EU `eu-central-1`, Cloud Run `europe-west3`, Postmark EU) | ✅ |

---

## 5. Roadmap técnico (Bloques)

Bloques 0 y 1 están cerrados (detalle en [`progress.md`](progress.md) y
[`progress-archive.md`](progress-archive.md)). Lo pendiente:

### Bloque 2 — Billing + simulator + diagnóstico

| Sub-PR | Qué incluye |
|---|---|
| 2.1 | Stripe (subscription = suelo, metered = overage) sobre el motor de [`billing-engine.md`](billing-engine.md) |
| 2.2 | Dashboard cliente: sección Facturación (plan + resoluciones usadas + historial) |
| 2.3 | Simulator auto-gen: user_profiles desde AOP + scenarios desde KB/transcripts |
| 2.4 | Simulator bulk runner + scheduled nightly + scenarios pre-built |
| 2.5 | Diagnostic Tools: Escalation Drivers + AOP Flow Analysis (drop-off por step) |
| 2.6 | Custom rubrics por tenant + scoring continuo de conversaciones reales + alerts |
| 2.7 | AI Data Assistant cliente: chat NL sobre métricas |
| 2.8 | Promotion gate: un AOP no se promueve sin pasar unit + integration + sims + rubrics |

### Bloque 3 — A/B + canary

| Sub-PR | Qué incluye |
|---|---|
| 3.1 | `agent_traffic_splits` por (tenant, AOP_version) + routing en el grafo |
| 3.2 | Production A/B con métricas comparativas (CSAT/deflection/volume) |
| 3.3 | Canary 5%→25%→50%→100% + rollback automático por threshold |

### Backlog (sin bloque asignado)

- Memory cross-conversación
- Detección automática de alucinaciones (refuerzo slow agent)
- Reapertura de conversaciones (`previous_conversation_id`)
- Voz/llamadas
- Intercom adapter (reactivo)
- WhatsApp directo vía Twilio (solo si un cliente sin helpdesk lo pide)
- Modo proactivo (carritos abandonados, upsell)
