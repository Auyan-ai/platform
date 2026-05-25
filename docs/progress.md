# Auyan — Estado del proyecto

_Última actualización: 2026-05-25 (sesión 39 — Bloque 0, sub-PR 0.11 Validación E2E: bugs deterministas arreglados offline; corrida final con judge PENDIENTE)_

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
| 0.10 | Simulator MVP | ✅ checkpoint E2E aprobado (CE-01 9.5, RE-01 7.5) |
| 0.11 | Validación E2E | 🔄 bugs deterministas arreglados offline · corrida final con judge PENDIENTE (sin crédito API) |

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

## Sub-PR 0.10 — Simulator MVP ✅ (checkpoint E2E aprobado)

**Diseño aprobado:** [`docs/simulator-design.md`](simulator-design.md). Estilo Decagon/Sierra: corre el grafo real contra conversaciones sintéticas, judge 4-dim, assertions programáticas.

**Fundación implementada y validada (sesión 37):**
- ✅ Migration `20260522000004_add_simulator_tables.sql` — `is_simulation` en conversations + 3 tablas (user_profiles, simulation_scenarios, simulation_runs) con RLS canónico. Validada contra Postgres local (10 índices, 3 RLS, 3 triggers, smoke insert OK). **Falta aplicar a staging.**
- ✅ `db/models.py` + `db/queries.py` — 3 modelos + CRUD + filtro `is_simulation = FALSE` en list/stale/nudge (protege al slow_agent de procesar conversaciones sintéticas).
- ✅ `simulator/mocks.py` — `MockShopifyAdapter` (fixtures por nombre de método). `simulator/assertions.py` — `check_assertions` puro. 16 tests nuevos.
- ✅ Cambios producción mínimos: `simulation_mode`/`simulation_fixtures` en AgentState, `commerce_mock` en SkillContext, inyección en `execute_skill`, 11 skills Shopify (`ctx.commerce_mock or ShopifyAdapter()`). **Descubrimiento clave:** el grafo NO hace I/O externo (helpdesk + Langfuse los hace el caller post-grafo), así que respond/escalate/finalize_trace NO se tocan.
- ✅ 914 tests existentes pasan (cero regresiones) + 16 nuevos. Ruff limpio.

**Implementado en sesión 38 (Sonnet):**
- ✅ `simulator/prompts.py` — SIMULATOR_PROMPT (Haiku) + SIM_JUDGE_SYSTEM_PROMPT (Opus) con prompt caching
- ✅ `simulator/transcript.py` — `SimulatorTranscript`, `TranscriptTurn`, `format_for_sim_judge`, `transcript_to_list`
- ✅ `simulator/user_simulator.py` — `UserSimulator` (Haiku 4.5, temperature=0.7, truncado a 5 turnos)
- ✅ `simulator/judge.py` — `SimulatorJudgeVerdict`, `judge_simulation()` (Opus 4.7 directo), `verdict_to_dict`
- ✅ `simulator/cost_guard.py` — `check_tenant_cost_cap` ($10/día) + `check_global_cost_cap` ($50/día) + rate limits (20 runs/h, 5 batches/h). **Sin Redis** — usa DB queries directamente.
- ✅ `simulator/runner.py` — `run_simulation()` + `run_batch()` + `_GLOBAL_SIM_SEMAPHORE(10)`. Loop detection, cost estimator.
- ✅ `simulator/scenarios/` — 4 personas + 25 scenarios (CE×8, RE×7, DE×6, EX×4) + `seed_scenarios()` idempotente
- ✅ `db/queries.py` — `get_global_sim_cost_cents_today()` + `soft_delete_conversation()` nuevas
- ✅ `routers/simulations.py` — 8 endpoints REST. Run único SYNC (timeout 60s). Batch ASYNC (batch_id pre-generado, polling).
- ✅ `main.py` — router registrado + `app.state.agent_deps` expuesto
- ✅ `pyproject.toml` — `simulator/scenarios/**` exento de E501
- ✅ 37 tests nuevos (user_simulator, judge, transcript, cost_guard, scenarios). **Suite total: 967/967 verde. Ruff limpio.**

**Checkpoint E2E APROBADO (sesión 38):** migration aplicada a staging ✅. CE-01 y RE-01 corridos contra el grafo real (tenant Lunaria) con `scripts/run_simulator.py`:
- **CE-01** (tracking): judge **9.5/10**, `get_order_status` ejecutada, tracking presente, 3 turnos.
- **RE-01** (devolución): judge **7.5/10**, `start_return` ejecutada con éxito, outcome=resolved, 2/2 assertions críticas.

**Bugs reales que el E2E destapó (todos arreglados):**
1. **Eco de roles** — `_build_messages` mapeaba customer→user/agent→assistant, pero el simulador ES el cliente, así que debe ser customer→assistant/agent→user. Con el mapeo invertido el cliente repetía las palabras del agente (bucle infinito). Además se descartan mensajes assistant iniciales (Anthropic exige empezar con user).
2. **Sin timeouts** — ni user_simulator ni judge tenían timeout; el runner no tenía tope global. Un run se colgó 18 min. Añadidos: 30s/llamada (simulator), 90s/llamada (judge), 180s tope global del run (`asyncio.wait_for`), 120s guard del judge.
3. **Mensaje vacío del simulador** — el modelo a veces devolvía `message=""`, rompiendo el embed del grafo y la API de Anthropic. Añadido retry-once + default a `give_up`, y skip de content vacío en `_build_messages`.
4. **`end_customer_id` faltante** — el runner no lo pasaba al initial_state del grafo → `load_conversation` explotaba. Corregido.
5. **`get_order_status` no exponía `line_items`** — el agente no tenía `line_item_id` para `start_return` y escalaba. Añadido `LineItemInfo` a `OrderDetail` (el dato ya venía del adapter). Hallazgo arquitectónico legítimo del simulador.

**Herramientas operativas nuevas:**
- `scripts/run_simulator.py` — CLI: seed scenarios + corre checkpoint (CE-01+RE-01) o `--scenario`/`--all`. Criterio checkpoint: judge ≥ 7 + assertions críticas.
- `scripts/seed_test_aops.py` — siembra AOPs `consulta_envio`/`returns`/`default` + habilita `start_return` para el tenant de prueba. `--update` reescribe (nueva versión).

**Decisión:** para el tenant de prueba se habilitó `shopify.start_return` sin aprobación humana (es L3 por defecto) para validar el flujo de resolución autónoma de devoluciones.

**Pendiente de 0.10:**
- UI super_admin (apps/web) — último (mover a Bloque 1 si no bloquea el lanzamiento)

---

## Sub-PR 0.11 — Validación E2E 🔄 (en progreso)

**Meta:** correr los 25 scenarios y alcanzar ≥80% (20/25) cumpliendo checkpoint (judge ≥ 7 + assertions críticas).

**Corrida completa de los 25 (sesión 39):** se agotó el saldo de la API de Anthropic a mitad del batch (error 400 `credit balance is too low`). Señal limpia solo de CE-01→CE-06 (corrieron antes del corte); CE-07→RE-07 murieron con `termination=error` (falsos negativos por crédito, no bugs). **La corrida final con judge queda PENDIENTE de recargar crédito.**

**Bugs arreglados offline (verificados — suite 972/972 verde, cero llamadas a API):**
1. **DE-04 (fixture, determinista)** — el mock de `update_shipping_address` devolvía `{"ok": True}` sin `id`, y la skill hace `order["id"]` → `KeyError`. Fixture corregido con forma realista de order. La skill se ejecuta y resuelve (verificado con crédito antes del corte: 1/1, `goal_achieved`).
2. **CE-05 (diseño de scenario)** — la assertion exigía `get_order_status` pero el cliente "vago" no daba número de pedido y no había fixture de email → insatisfacible. Se agregó `#1234` al mensaje inicial preservando la confusión envío-vs-entrega.
3. **Gap del harness `must_escalate: False`** — `check_assertions` solo evaluaba `must_escalate` cuando era `True`; con `False` (CE-02 espera NO escalar) se ignoraba en silencio. Ahora honra ambos valores como crítica + test nuevo.
4. **Inyección de fecha actual (hallazgo arquitectónico)** — `build_system_prompt` nunca inyectaba "hoy", así que el agente adivinaba la fecha. Rompía **en silencio** todo cálculo de fechas: tiempo de preparación (CE-02) y la ventana de 30 días de devoluciones (`returns` / RE-01 / RE-02). Ahora se inyecta `Fecha actual: YYYY-MM-DD` en el system prompt (param opcional retrocompatible; `reason` pasa `datetime.now(UTC)`). Probablemente desbloquea varios scenarios de returns.
5. **CE-02 (comportamiento, AOP)** — el transcript mostró que el cliente "impaciente" exageraba ("llevo una semana") con un pedido de 2 días, y el agente caía y escalaba. Reforzados los guardrails de `consulta_envio`: impaciencia ≠ motivo de escalado; usar `created_at` para aterrizar al cliente con el dato real. **A validar con API.**

**Infra de costo de tests (nueva):**
- `run_simulator.py --no-judge` — salta el judge (Opus, el grueso del costo); solo corre Sonnet (agente) + Haiku (simulador). Para cazar bugs de assertions/fixtures barato. La corrida final SIEMPRE usa judge.
- `run_simulator.py --reseed` — actualiza `mock_fixtures`/`assertions` de los scenarios que ya existen en DB (antes se saltaban por idempotencia, por eso los edits a fixtures no aplicaban). Implementado vía `seed_scenarios(reseed=True)` + `update_simulation_scenario()` en queries.

**PENDIENTE de 0.11 (necesita crédito API):**
1. Re-seed AOPs: `seed_test_aops.py --tenant <Lunaria> --update` (cambiaron guardrails de `consulta_envio`).
2. Mapa de assertions sin gastar en judge: `run_simulator.py --tenant <Lunaria> --reseed --no-judge --all`.
3. Arreglar lo que quede y **corrida final con judge** para confirmar ≥20/25.

Tenant de prueba (Lunaria staging): `11111111-1111-1111-1111-111111111111`.

---

## Empezar aquí — siguiente sesión

**Modelo recomendado:** **Sonnet** para terminar 0.11 (re-correr simulador + pulir AOPs).

**Estado Bloque 0:** 0.1–0.10 completados ✅. **0.11 en progreso** 🔄 — bugs deterministas arreglados offline (suite 972/972 verde), falta la corrida final con judge (BLOQUEADA por crédito API). Pendiente:
1. **Recargar crédito API Anthropic** — bloquea cualquier corrida del simulador.
2. **0.11** terminar validación E2E: re-seed AOPs (`--update`) → `--reseed --no-judge --all` → arreglar lo que quede → corrida final con judge (meta ≥20/25). Detalle en la sección Sub-PR 0.11 arriba.
3. **UI simulator** (apps/web) — puede moverse a Bloque 1 si no bloquea el lanzamiento

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
