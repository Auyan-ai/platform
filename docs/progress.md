# Auyan — Estado del proyecto

_Última actualización: 2026-05-24 (sesión 36 — Bloque 0, sub-PR 0.8 Roles internos DB completado)_

> Historial completo de Sprints 1-11 y Rate Limiting en [`docs/progress-archive.md`](progress-archive.md).

---

## Stack y decisiones clave

| Decisión | Elegida | Razón |
|---|---|---|
| Backend | FastAPI Python 3.12 | Compatibilidad ML/AI, velocidad |
| Frontend | Next.js 15 + TypeScript + Tailwind v4 + shadcn | App Router, SSR, tipado |
| DB | Supabase (Postgres + pgvector + Auth + RLS) | pgvector, RLS nativo |
| Agente | LangGraph + Claude API | Control fino del grafo, estado persistente |
| Observabilidad | Langfuse | Trazabilidad por tenant, open source |
| Deploy | Railway | Simplicidad operativa |
| Multi-tenancy | `tenant_id` en todas las tablas + RLS | Seguro, simple |
| Modelos | Sonnet default · Opus para L3/supervisor/arquitectura · Haiku para intent | Costo/calidad |

---

## Historial pre-pivot (Sprints 1-11 + Rate Limiting)

| Sprint | Foco | PRs clave | Tests finales |
|---|---|---|---|
| 0 | Monorepo + CLAUDE.md | #1 | — |
| 1 | FastAPI + LangGraph + Railway staging | #4, #6, #9-10 | 127 |
| 2 | asyncpg + auth JWT ES256 + endpoints admin | #12-16 | 182 |
| 3 | Dashboard super_admin Next.js | #19-29 | — |
| 4 | Dashboard tenant_admin read-only | #31, #37-39 | 189 |
| 5 | Fix bugs grafo | #40 | 193 |
| 6 | Skills framework + Shopify L1 + ReAct loop | #44, #46-47, #49, #51 | 331 |
| 7 | AOPs DB + intent selector + UI editor + eval harness | #56-57 + varias | 450 |
| 8 | Agent Reasoning UI + Supervisor pattern | #59, #60, #62-63 | 478 |
| 9 | Idempotency + L2 skills + Audit PII + AOP cache + Nudges | #68-74 | 560 |
| 10 | Skills L3 + Human Approval Gate + UI aprobaciones | #75 | 628 |
| 11 | Slow Agent end-to-end | #76 | 628 |
| Rate Limiting | Rate limit + budget diario + message cap + UI consumo | #77-81 | 711 |

---

## Pivot 2026-05-22 — BPO → Managed AI Service

**ANTES:** BPO con agentes humanos internos atendiendo tickets escalados.
**AHORA:** **Managed AI Service** — el cliente conserva su equipo CX para escalados; Auyan es el equipo externo de Agent Engineers que configura, mantiene y optimiza el agente IA.

Implicaciones: `tenant_agent` removido · Chatwoot → opcional al cliente · Dashboard interno = panel operativo cross-tenant · 25 decisiones cerradas → ver [`docs/auyan-master-context.md`](auyan-master-context.md) y [`docs/progress-archive.md`](progress-archive.md#pivot-2026-05-22--bpo--managed-ai-service).

---

## Bloque 0 — Sanity check + fundación arquitectónica

### Estado

| # | Foco | Estado |
|---|---|---|
| 0.1 | Hard removal `tenant_agent` | ✅ [PR #83](https://github.com/Auyan-ai/platform/pull/83)+[#84](https://github.com/Auyan-ai/platform/pull/84) |
| 0.2 | Framework adapters base | ✅ [PR #87](https://github.com/Auyan-ai/platform/pull/87) |
| 0.3 | ShopifyAdapter stateless | ✅ [PR #89](https://github.com/Auyan-ai/platform/pull/89) |
| 0.4 | ChatwootAdapter stateless + webhook | ✅ [PR #90](https://github.com/Auyan-ai/platform/pull/90) |
| 0.5 | ZendeskAdapter + OAuth flow + webhook | ✅ [PR #91](https://github.com/Auyan-ai/platform/pull/91) |
| 0.6 | GorgiasAdapter + OAuth (helpdesk #1) | ✅ [PR #92](https://github.com/Auyan-ai/platform/pull/92) |
| 0.7 | PostmarkEmailAdapter outbound | ✅ (commit c80ccdd) |
| 0.8 | Roles internos DB | ✅ [PR #94](https://github.com/Auyan-ai/platform/pull/94) |
| 0.9 | AOPs `steps[]` opcional + events | ✅ (sesión 35) |
| 0.10 | Simulator MVP | ⏳ **Opus** |
| 0.11 | Validación E2E | ⏳ último |

### Sub-PR 0.1 — Hard removal `tenant_agent` ✅

- Migración: `user_role` enum reconstruido sin `tenant_agent`, usuarios migrados a `tenant_admin`
- `UserRole = Literal["super_admin", "tenant_admin"]` en API y shared
- Tests adaptados por intent (no search-and-replace): 3 eliminados, 1 migrado
- **Suite total: 718/718 verde**

**Lección:** Para rebuild de enum con CHECK constraint — DROP CONSTRAINT antes de `ALTER COLUMN TYPE text`. El cast del viejo tipo persiste en la expresión de la constraint y explota si se hace en el orden incorrecto.

### Sub-PR 0.2 — Framework adapters base ✅

| Archivo | Qué hace |
|---|---|
| `integrations/base.py` | Protocols `MessageProvider`, `HelpdeskProvider`, `CommerceProvider` + dataclasses `InboundMessage`, `ExternalTicketRef`, `IntegrationContext` |
| `integrations/registry.py` | `IntegrationRegistry` singleton con `@register(kind, provider)` decorator |
| `services/integrations_crypto.py` | AES-256-GCM: `encrypt_credentials`, `decrypt_credentials` (nonce 12 bytes) |
| `supabase/migrations/20260522000002_add_tenant_integrations.sql` | Tabla `tenant_integrations` con `credentials_encrypted BYTEA`, RLS, índices |
| `db/models.py` + `db/queries.py` | `TenantIntegration` + CRUD completo |

**Suite total: 747/747. Migración + `INTEGRATIONS_SECRET_KEY` en Railway staging ✅**

### Sub-PR 0.3 — ShopifyAdapter stateless ✅

- `ShopifyClient` singleton → `ShopifyAdapter` stateless que implementa `CommerceProvider`
- `_client(ctx)` construye `ShopifyClient` con creds del tenant por llamada
- Registrado como `commerce/shopify`; tests Shopify (11 skills) adaptados
- **Suite total: 747/747**

### Sub-PR 0.4 — ChatwootAdapter stateless ✅

| Archivo | Qué se hizo |
|---|---|
| `integrations/chatwoot.py` | `ChatwootClient` stateless (constructor en lugar de singleton settings) + `ChatwootAdapter` implementa `HelpdeskProvider` completo |
| `db/queries.py` | `get_integration_by_chatwoot_account` — lookup cross-tenant por `config->>'account_id'` |
| `routers/webhooks_chatwoot.py` | `POST /webhooks/chatwoot`: filtra event/type, resuelve tenant, valida firma opcional, ejecuta flujo inbound + `send_outbound`. Idempotencia con key `chatwoot:{message_id}` |

**Credentials:** `{ "api_access_token": "...", "webhook_secret_token": "..." }`
**Config:** `{ "base_url": "https://app.chatwoot.com", "account_id": "1", "escalation_team_id": "5" }`
**Suite total: 777/777 verde**

### Sub-PR 0.5 — ZendeskAdapter + OAuth flow ✅

| Archivo | Qué se hizo |
|---|---|
| `integrations/zendesk.py` | `ZendeskClient` (HTTP stateful, Bearer Auth) + `ZendeskAdapter` (stateless, `HelpdeskProvider`) + `verify_zendesk_signature` HMAC-SHA256+base64. Registrado como `helpdesk/zendesk`. |
| `db/queries.py` | `get_integration_by_zendesk_subdomain` — lookup cross-tenant por `config->>'subdomain'` |
| `routers/oauth_zendesk.py` | `GET /oauth/zendesk/authorize` (redirect con state HMAC firmado, TTL 15min) + `GET /oauth/zendesk/callback` (intercambia code, persiste token cifrado) |
| `routers/webhooks_zendesk.py` | `POST /webhooks/zendesk`: extrae subdomain, resuelve tenant, valida firma HMAC opcional, flujo inbound + `send_outbound`. Idempotencia con key `zendesk:{ticket_id}` |
| `core/config.py` | `zendesk_oauth_client_id/secret/redirect_uri` opcionales |

**Credentials:** `{ "oauth_token": "...", "webhook_signing_secret": "..." }`
**Config:** `{ "subdomain": "miempresa", "escalation_group_id": "123" }`

**Payload requerido en Zendesk Trigger:**
```json
{
  "ticket_id": "{{ticket.id}}", "subject": "{{ticket.title}}",
  "content": "{{ticket.latest_comment_html_stripped}}",
  "requester_email": "{{ticket.requester.email}}",
  "requester_name": "{{ticket.requester.name}}",
  "subdomain": "hardcoded-subdomain"
}
```

**Suite total: 807/807 verde. Ruff limpio.**

**Pendiente de staging 0.5:**
- [ ] Registrar OAuth app en Zendesk Developer Portal → obtener `client_id` + `client_secret`
- [ ] Setear `ZENDESK_OAUTH_CLIENT_ID/SECRET/REDIRECT_URI` en Railway staging
- [ ] Test flujo OAuth end-to-end + webhook con tenant de prueba

### Sub-PR 0.6 — GorgiasAdapter + OAuth flow ✅

| Archivo | Qué se hizo |
|---|---|
| `integrations/gorgias.py` | `GorgiasClient` (HTTP stateful, domain + Bearer token) + `GorgiasAdapter` (stateless, `HelpdeskProvider`) + `verify_gorgias_signature` HMAC-SHA256 base64 (`X-Gorgias-Hmac-Sha256`). Registrado como `helpdesk/gorgias`. |
| `db/queries.py` | `get_integration_by_gorgias_domain` — lookup cross-tenant por `config->>'domain'` |
| `routers/oauth_gorgias.py` | `GET /oauth/gorgias/authorize` (state HMAC firmado, TTL 15min) + `GET /oauth/gorgias/callback` (intercambia code, persiste token cifrado) |
| `routers/webhooks_gorgias.py` | `POST /webhooks/gorgias`: filtra `from_agent=false`, lookup por domain, valida firma opcional, idempotencia `gorgias:{ticket_id}:{message_id}`, flujo inbound + `send_outbound` si decide responder |
| `core/config.py` | `gorgias_oauth_client_id/secret/redirect_uri` opcionales |

**35 tests nuevos** (23 adapter + 12 oauth). **Suite total: 842/842 verde. Ruff limpio.**

**Pendiente de staging 0.6:**
- [ ] Registrar app en Gorgias Developer Portal → obtener `client_id` + `client_secret`
- [ ] Setear `GORGIAS_OAUTH_CLIENT_ID/SECRET/REDIRECT_URI` en Railway staging
- [ ] Test flujo OAuth end-to-end + webhook con tenant de prueba

### Sub-PR 0.7 — PostmarkEmailAdapter + EmailSender ✅

| Archivo | Qué se hizo |
|---|---|
| `integrations/postmark.py` | `PostmarkClient` HTTP con retry tenacity (5xx/429/timeouts) + `PostmarkEmailAdapter` global (no per-tenant) + `build_postmark_adapter(settings)` factory |
| `services/email_templates/escalation_fallback.py` | `render(...)` → `(subject, text_body, html_body)` para notificar al CX del cliente cuando el agente escala sin helpdesk configurado |
| `services/email_sender.py` | `EmailSender` fire-and-forget (mismo patrón que `AuditLogger`): no-op si `POSTMARK_API_TOKEN` no configurado, silencia errores del envío |
| `core/config.py` | `postmark_from_email` + `postmark_from_name` (defaults: `noreply@auyan.ai` / `Auyan`) |
| `main.py` | `EmailSender` wired en lifespan como `app.state.email_sender` |
| `.env.example` | `POSTMARK_FROM_EMAIL` + `POSTMARK_FROM_NAME` documentadas |

**Decisión de diseño:** Postmark usa credenciales globales de Auyan (no per-tenant). No va al `IntegrationRegistry` — es un servicio de notificación, no una integración bidireccional por tenant.

**24 tests nuevos. Suite total: 866/866 verde. Ruff limpio.**

**Pendiente de staging 0.7:**
- [ ] Setear `POSTMARK_API_TOKEN` + `POSTMARK_FROM_EMAIL` en Railway staging
- [ ] Verificar dominio `auyan.ai` en Postmark → sender signature

### Sub-PR 0.8 — Roles internos estructura DB ✅

| Archivo | Qué se hizo |
|---|---|
| `supabase/migrations/20260522000003_add_internal_users.sql` | `internal_role` ENUM (5 valores) + tablas `internal_users`, `tenant_assignments`, `role_permissions` + seed 47 permisos + RLS |
| `db/models.py` | `InternalUser`, `TenantAssignment`, `RolePermission` |
| `db/queries.py` | 12 funciones: CRUD `internal_users` + `user_has_permission()` + `get_permissions_for_user()` + assignments CRUD |
| `core/security.py` | `InternalAuthContext` + `get_internal_auth_context` (lookup en `internal_users`) + `require_internal_permission` dep factory |

**Diseño:** `internal_users` es tabla separada de `users` (clientes). Mismo Supabase Auth, distinto perfil de negocio. El flujo de auth de clientes (`get_auth_context`) no fue tocado.

**Permisos:** 5 roles (super_admin con todos, aide técnico scoped, qa_km transversal, ops_manager reportes/billing, cs_manager solo lectura comercial). Matriz ajustable vía INSERT/DELETE sin migración de schema.

**28 tests nuevos. Suite total: 914/914 verde. Ruff limpio. Migración aplicada en staging ✅**

---

### Sub-PR 0.9 — AOPs `steps[]` opcional + events ✅

| Archivo | Qué se hizo |
|---|---|
| `db/models.py` | `ReasoningEventType` extendido con `"step_entered"` y `"step_completed"` |
| `aops/compiler.py` | `AopStep` dataclass + campo `steps` en `CompiledAOP` + `_parse_steps` + `_render_steps` |
| `agents/state.py` | Campo `aop_steps: list[dict]` en `AgentState` |
| `agents/nodes/select_aop.py` | Añade `aop_steps` al output (lista de steps serializados del AOP compilado) |
| `agents/nodes/reason.py` | Emite `step_entered` antes del LLM call; `step_completed` al cierre de cada iteración (con outcome = decision o `tool:<slug>`) |

**Backward compat total:** AOPs sin `steps[]` siguen funcionando idéntico — `aop_steps` queda vacío y ningún step event se emite.

**AOP YAML con steps[] (ejemplo):**
```yaml
steps:
  - id: gather_info
    name: Recopilar información del pedido
    decision_point: ¿Tenemos número de pedido o email?
  - id: check_status
    name: Verificar estado
    decision_point: ¿El pedido está en tránsito?
  - id: resolve
    name: Resolver y responder
```

**48 tests nuevos. Suite total: 914/914 verde. Ruff limpio.**

---

## Plan de construcción post-pivot

### Bloque 1 — Sprint A: habilita vender (5-7 semanas)

`tenant_playbook` · `tenant_facts` · Onboarding wizard 9 pasos · KB drop-zone · Reporte semanal · Dashboard cliente 7 secciones MVP · Dashboard super_admin Home/Review Queue · `apps/landing` + Aceternity UI · Email outbound templates

### Bloque 2 — Duet + Billing + UI pulida (6-8 semanas)

Stripe Subscriptions · Dashboard cliente Facturación · Simulator auto-gen · Bulk runner · Diagnostic Tools · Watchtower · AI Data Assistant cliente

### Bloque 3 — Producción A/B + canary (6-8 semanas)

`agent_traffic_splits` · Production A/B · Canary ramp 5%→100% + rollback · Overage automation

### Bloque 4 — Backlog futuro

Memory cross-conversación · Detección automática alucinaciones · Reapertura conversaciones · Intercom adapter · WhatsApp directo · Modo proactivo · MCP server

---

## Empezar aquí — siguiente sesión

**Modelo recomendado:** Sonnet para 0.11; **Opus para 0.10 (Simulator)**.

**Estado Bloque 0:** 0.1–0.9 completados ✅. Pendiente:
1. **0.10** Simulator MVP — **Opus**
2. **0.11** Validación E2E — último paso del bloque

**Pendiente de staging (PRs ya mergeables):**
- [ ] PR #94 (0.8): migración aplicada ✅ — mergear a develop
- [ ] Registrar OAuth apps en Gorgias + Zendesk Developer Portals
- [ ] Setear `POSTMARK_API_TOKEN` + dominio `auyan.ai` en Postmark

### Referencias

- [`docs/auyan-master-context.md`](auyan-master-context.md) — fuente única de verdad negocio + producto
- [`docs/architecture-agent-v2.md`](architecture-agent-v2.md) sección 20 — arquitectura técnica post-pivot
- [`docs/bloque-0-plan.md`](bloque-0-plan.md) — plan detallado todos los sub-PRs Bloque 0
- [`docs/progress-archive.md`](progress-archive.md) — historial completo Sprints 1-11 + pivot
- `CLAUDE.md` (raíz) — reglas operativas del proyecto
