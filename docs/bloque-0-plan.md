# Bloque 0 — Plan de ejecución detallado

> Sanity check + fundación arquitectónica post-pivot 2026-05-22.
> Duración esperada: **3-4 semanas** de trabajo concentrado.
> Modelo original del plan: Sonnet salvo el diseño inicial del simulator. El criterio vigente para 0.11A usa Sonnet por defecto y Opus solo para calibración explícita.
> **Estado histórico:** este documento conserva el plan original de Bloque 0. No usarlo como plan activo. El estado operativo vigente vive en [`docs/progress.md`](progress.md), donde 0.11 fue reencuadrado como Agent Verification Staging con LangSmith, simulator costeado, Shopify real y Chatwoot primero.

---

## Objetivo

Dejar el sistema preparado arquitectónicamente para el modelo Managed AI Service, con la deuda crítica eliminada y la infraestructura de adapters/simulator lista. Sin esto, no puedes:

- Onboardear cliente 2 (rompe multi-tenancy real con helpdesks distintos)
- Validar el sistema actual con confianza antes de prometérselo a cliente FP
- Construir Bloque 1 (Sprint A) sobre fundación rota

## Dependencias externas (en paralelo con Bloque 0 técnico)

- **Fase 0 LEGAL:** Constitución Auyan SL, pacto socios, asesor fiscal, cuenta bancaria, decisión paro esposa, plantillas DPA/T&C/Privacy.
- **OAuth Partner registrations** (necesarios para sub-PRs 0.5/0.6):
  - Shopify Partner Program (gratis, ~2h)
  - Gorgias Developer Account + crear app draft (~4h)
  - Zendesk OAuth client + redirect URI (~4h)

Estos NO bloquean código pero sí bloquean tests E2E con OAuth real.

---

## Criterios de done global del Bloque 0

1. **Sistema actual validado E2E** con simulator contra Shopify integration + grafo + skills L1/L2/L3 + supervisor + slow agent.
2. **`tenant_agent` removido** sin tests rotos.
3. **3 helpdesks bidireccionales operativos** (Gorgias, Chatwoot, Zendesk) con OAuth o API key, gestionables por tenant en DB.
4. **`tenant_integrations` table en producción** con credentials cifrados.
5. **Roles internos estructura DB lista** (todos siguen siendo super_admin operacionalmente, pero el esquema soporta diferenciación).
6. **Simulator MVP funcionando** con scenarios manuales + judge 4-dim.
7. **Toda la suite de tests pasa.** Cero regresiones.
8. **Documentación actualizada** (CHANGELOG por sub-PR + README updates si aplica).

---

## Métricas de éxito

| Métrica | Target |
|---|---|
| Tests pasando | 100% (actual 628+ + nuevos ~80-100) |
| Cobertura de adapters | 4 (Shopify + Chatwoot + Zendesk + Gorgias + Postmark out) |
| Simulations corriendo | Al menos 20 scenarios manuales con pass rate ≥ 80% |
| Bugs descubiertos en validación E2E | Documentados y fixeados o trackeados |
| `tenant_agent` referencias | 0 en código de producción |
| Tiempo total | ≤ 4 semanas |

---

## Sub-PRs — orden, dependencias y detalle

### Sub-PR 0.1 — Hard removal `tenant_agent`

**Cuándo:** Primero. Descarga código antes de refactor mayor.
**Modelo:** Sonnet.
**Dependencias:** ninguna.
**Tiempo estimado:** 1-2 días.

**Archivos a tocar:**

- `supabase/migrations/20260522000001_remove_tenant_agent_role.sql` (nuevo):
  ```sql
  UPDATE users SET role = 'tenant_admin' WHERE role = 'tenant_agent';
  CREATE TYPE user_role_new AS ENUM ('super_admin', 'tenant_admin');
  ALTER TABLE users ALTER COLUMN role DROP DEFAULT;
  ALTER TABLE users ALTER COLUMN role TYPE user_role_new USING role::text::user_role_new;
  DROP TYPE user_role;
  ALTER TYPE user_role_new RENAME TO user_role;
  ALTER TABLE users ALTER COLUMN role SET DEFAULT 'tenant_admin';
  ```
- `apps/api/db/models.py`: `UserRole = Literal["super_admin", "tenant_admin"]`
- `apps/api/core/security.py`: actualizar docstrings + comentarios (líneas 14, 264, 278)
- `apps/api/tests/test_security.py`: revisar ~25 referencias (re-evaluar intent test por test, NO search-and-replace)
- `apps/api/tests/test_metrics.py`: `test_tenant_agent_gets_403` → eliminar o adaptar
- `apps/api/tests/test_escalations.py`: línea 59 `UserRecord(role="tenant_agent")` → cambiar a `tenant_admin`
- `apps/web/app/(dashboard)/page.tsx:23`: comentario
- `CLAUDE.md` raíz: revisar si menciona `tenant_agent`

**Tests a actualizar:**
- Eliminar tests que validan SOLAMENTE el comportamiento `tenant_agent` (que ya no existe)
- Adaptar tests que validan diferencias entre `tenant_admin` y `tenant_agent` → consolidar en `tenant_admin`
- Validar que rights de `tenant_admin` incluyen lo que antes hacía `tenant_agent`

**Criterio done:**
- 0 referencias a `tenant_agent` en grep recursivo
- Migration aplicada en staging
- Tests suite pasa al 100%
- PR mergeado a develop

---

### Sub-PR 0.2 — Framework adapters base

**Cuándo:** Inmediatamente después de 0.1. **Fundacional — todo lo demás depende.**
**Modelo:** Sonnet (patrón claro, baja ambigüedad).
**Dependencias:** 0.1 mergeado.
**Tiempo estimado:** 3-4 días.

**Archivos a crear:**

- `supabase/migrations/20260522000002_add_tenant_integrations.sql`:
  ```sql
  CREATE TABLE tenant_integrations (
      id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id             UUID NOT NULL REFERENCES tenants(id),
      kind                  TEXT NOT NULL,
      provider              TEXT NOT NULL,
      credentials_encrypted BYTEA NOT NULL,
      config                JSONB NOT NULL DEFAULT '{}',
      is_active             BOOLEAN NOT NULL DEFAULT TRUE,
      is_primary_for_kind   BOOLEAN NOT NULL DEFAULT FALSE,
      enabled_at            TIMESTAMPTZ,
      enabled_by            UUID,
      created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      deleted_at            TIMESTAMPTZ,
      CONSTRAINT kind_valid CHECK (kind IN ('helpdesk', 'commerce', 'channel', 'llm'))
  );
  CREATE UNIQUE INDEX tenant_integrations_unique_active 
      ON tenant_integrations (tenant_id, kind, provider) 
      WHERE deleted_at IS NULL;
  -- RLS por tenant
  ALTER TABLE tenant_integrations ENABLE ROW LEVEL SECURITY;
  CREATE POLICY tenant_integrations_isolation ON tenant_integrations
      USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
  ```

- `apps/api/integrations/base.py` (nuevo):
  ```python
  class IntegrationContext(BaseModel):
      tenant_id: UUID
      credentials: dict
      config: dict
  
  class MessageProvider(Protocol):
      async def parse_inbound_webhook(self, payload) -> InboundMessage: ...
      async def send_outbound(self, ctx, conversation_ref, content, attachments=None) -> None: ...
  
  class HelpdeskProvider(MessageProvider, Protocol):
      async def add_internal_note(self, ctx, ticket_ref, content) -> None: ...
      async def assign_to_human(self, ctx, ticket_ref, reason) -> None: ...
      async def update_status(self, ctx, ticket_ref, status) -> None: ...
      async def push_escalation(self, ctx, conversation, reason, agent_context) -> ExternalTicketRef: ...
  
  class CommerceProvider(Protocol):
      # métodos comunes commerce (orders, products, customers)
      ...
  ```

- `apps/api/integrations/registry.py` (nuevo): paralelo al `SkillRegistry`, con decorator `@IntegrationRegistry.register(kind, provider)`.

- `apps/api/services/integrations_crypto.py` (nuevo): cifrado/descifrado AES-GCM con salt por tenant. Salt vive en `tenant_secrets` (ya existe Sprint 9.3).

- `apps/api/db/queries.py`: queries para `tenant_integrations` (get, list, upsert, soft_delete, get_by_kind_active).

- `apps/api/db/models.py`: `TenantIntegration`, `IntegrationContext` Pydantic.

**Tests a crear:**
- `test_tenant_integrations.py`: CRUD + crypto + RLS por tenant
- `test_integration_registry.py`: register, get, fallback

**Criterio done:**
- Tabla `tenant_integrations` aplicada en staging
- Crypto round-trip (encrypt → decrypt → match) verificado
- RLS verificado: tenant A no ve integraciones de tenant B
- 20+ tests nuevos pasan

---

### Sub-PR 0.3 — Refactor `ShopifyAdapter` ✅ [PR #89](https://github.com/Auyan-ai/platform/pull/89)

**Cuándo:** Después de 0.2.
**Modelo:** Sonnet.
**Dependencias:** 0.2 (framework adapters).
**Tiempo estimado:** 2-3 días.

**Cambios principales:**

- `apps/api/integrations/shopify.py`: refactor de `ShopifyClient(singleton)` → `ShopifyAdapter` que implementa `CommerceProvider` y recibe `IntegrationContext` en cada método.
- Skills `shopify.*` actualizadas para resolver `ShopifyAdapter` por tenant en runtime via `IntegrationRegistry.get('commerce', 'shopify')` + `tenant_integrations.get_by_kind('commerce', tenant_id)`.
- Tests `test_shopify_*.py`: usar `MockShopifyAdapter` por tenant en lugar de mocks globales.

**Criterio done:**
- Tests existentes Shopify (11 skills) pasan adaptados
- Smoke test: dos tenants distintos pueden conectar Shopify stores distintas

---

### Sub-PR 0.4 — Refactor `ChatwootAdapter` ✅ [PR #90](https://github.com/Auyan-ai/platform/pull/90)

**Cuándo:** Paralelo a 0.3 (independiente).
**Modelo:** Sonnet.
**Dependencias:** 0.2.
**Tiempo estimado:** 2-3 días.

**Cambios principales:**

- `apps/api/integrations/chatwoot.py`: refactor a `ChatwootAdapter(HelpdeskProvider)`.
- Implementar métodos faltantes del protocol:
  - `parse_inbound_webhook` (parseo del webhook de Chatwoot)
  - `send_outbound` (refactor de `send_message`)
  - `add_internal_note` (nuevo — `private: true` en Chatwoot API)
  - `assign_to_human` (refactor de `assign_conversation`)
  - `update_status` (cambiar status Chatwoot)
  - `push_escalation` (combinar `add_internal_note` + status + assignment)
- Webhook endpoint en `routers/webhooks_chatwoot.py` (nuevo).

**Tests:**
- `test_chatwoot_adapter.py`: cada método del protocol con mock HTTP

---

### Sub-PR 0.5 — Refactor `ZendeskAdapter` + OAuth 🔁 [PR #91](https://github.com/Auyan-ai/platform/pull/91) en review

**Cuándo:** Paralelo a 0.3/0.4.
**Modelo:** Sonnet.
**Dependencias:** 0.2 + Zendesk OAuth app creada externamente.
**Tiempo estimado:** 3-4 días.

**Cambios:**

- `apps/api/integrations/zendesk.py`: refactor a `ZendeskAdapter(HelpdeskProvider)`.
- Implementar OAuth Authorization Code flow:
  - `apps/api/routers/oauth_zendesk.py` (nuevo): `GET /oauth/zendesk/authorize` (redirect) + `GET /oauth/zendesk/callback` (token exchange + persist)
  - Refresh token logic (Zendesk tokens caducan)
- Implementar todos los métodos del protocol.
- Webhook endpoint en `routers/webhooks_zendesk.py` (nuevo).

**Tests:**
- `test_zendesk_adapter.py`: protocol completo
- `test_zendesk_oauth.py`: flow OAuth con mock callback

---

### Sub-PR 0.6 — Nuevo `GorgiasAdapter` + OAuth

**Cuándo:** Paralelo a 0.5.
**Modelo:** Sonnet.
**Dependencias:** 0.2 + Gorgias OAuth app creada externamente.
**Tiempo estimado:** 3-4 días.

**Archivos nuevos:**

- `apps/api/integrations/gorgias.py`: `GorgiasAdapter(HelpdeskProvider)` desde cero.
- `apps/api/routers/oauth_gorgias.py`: OAuth2 flow.
- `apps/api/routers/webhooks_gorgias.py`: webhook handler.
- `apps/api/tests/test_gorgias_adapter.py`: protocol completo.
- `apps/api/tests/test_gorgias_oauth.py`: flow OAuth con mock.

**Criterio done:**
- Smoke test: registrar app en Gorgias staging → OAuth flow completo → ticket recibido → respuesta enviada → internal note posteada

---

### Sub-PR 0.7 — `PostmarkEmailAdapter` outbound

**Cuándo:** Paralelo a helpdesks.
**Modelo:** Sonnet.
**Dependencias:** 0.2.
**Tiempo estimado:** 1-2 días.

**Nota:** este adapter es para **email outbound de Auyan → cliente** (reportes, notificaciones lifecycle, escalaciones cuando no hay helpdesk). NO es customer-facing del cliente final.

**Archivos:**

- `apps/api/integrations/postmark.py`: `PostmarkEmailAdapter(MessageProvider)`.
- Templates Jinja2 base en `apps/api/services/email_templates/`.
- `apps/api/services/email_sender.py`: queue + retry logic.

---

### Sub-PR 0.8 — Roles internos estructura DB

**Cuándo:** Paralelo a adapters.
**Modelo:** Sonnet.
**Dependencias:** 0.1 (tenant_agent removido primero).
**Tiempo estimado:** 2 días.

**Archivos:**

- `supabase/migrations/20260522000003_add_internal_users.sql`:
  ```sql
  CREATE TYPE internal_role AS ENUM (
      'super_admin', 'aide', 'qa_km', 'ops_manager', 'cs_manager'
  );
  
  CREATE TABLE internal_users (
      id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      auth_user_id  UUID UNIQUE NOT NULL,  -- ref a Supabase Auth
      name          TEXT NOT NULL,
      email         TEXT UNIQUE NOT NULL,
      role          internal_role NOT NULL DEFAULT 'aide',
      is_active     BOOLEAN NOT NULL DEFAULT TRUE,
      created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      deleted_at    TIMESTAMPTZ
  );
  
  CREATE TABLE tenant_assignments (
      id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id         UUID NOT NULL REFERENCES tenants(id),
      internal_user_id  UUID NOT NULL REFERENCES internal_users(id),
      role_in_tenant    TEXT NOT NULL,
      assigned_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      assigned_by       UUID,
      unassigned_at     TIMESTAMPTZ
  );
  CREATE UNIQUE INDEX tenant_assignments_active 
      ON tenant_assignments (tenant_id, internal_user_id, role_in_tenant)
      WHERE unassigned_at IS NULL;
  
  CREATE TABLE role_permissions (
      role       internal_role NOT NULL,
      permission TEXT NOT NULL,
      PRIMARY KEY (role, permission)
  );
  -- Seed permisos por rol según matriz definida
  ```

- `apps/api/db/models.py`: `InternalUser`, `TenantAssignment`, `RolePermission`.
- `apps/api/db/queries.py`: queries básicas + `user_has_permission(user_id, permission)`.
- `apps/api/core/security.py`: middleware actualizado para chequear permisos por rol interno.
- **Seed inicial:** Kenny y esposa como `super_admin`. No tocan auth flow del cliente.

**Tests:**
- `test_internal_users.py`: CRUD + permisos por rol
- `test_tenant_assignments.py`: asignación + filtrado por rol

**Criterio done:**
- Tablas aplicadas en staging
- Kenny y esposa seedeados como `super_admin`
- `user_has_permission` funcionando
- Lógica de filtrado del Home/Review Queue lista para usar (aunque el componente UI viene en Bloque 1)

---

### Sub-PR 0.9 — AOPs `steps[]` opcional + events

**Cuándo:** Final del Bloque 0 (después de adapters).
**Modelo:** Sonnet.
**Dependencias:** ninguna directa.
**Tiempo estimado:** 0.5-1 día.

**Cambios:**

- `apps/api/aops/compiler.py`: schema YAML del AOP ahora acepta campo opcional `steps[]` con `{id, name, decision_point}`.
- `apps/api/agents/nodes/`: nodos relevantes emiten `step_entered(step_id)` y `step_completed(step_id, outcome)` cuando el AOP tiene `steps[]` definido.
- `apps/api/services/reasoning.py`: extiende `agent_reasoning_events` para incluir nuevos tipos.

**Criterio done:**
- AOP con `steps[]` válido se compila sin errores
- AOP sin `steps[]` (legacy) sigue funcionando idéntico
- Events emitidos quedan en `agent_reasoning_events` con tipos nuevos
- Dashboard de Flow Analysis NO se construye aquí — solo se acumulan datos para Bloque 2

---

### Sub-PR 0.10 — Simulator MVP

**Cuándo:** Después de adapters refactorizados. **Pieza más grande de Bloque 0.**
**Modelo original:** Opus para diseño del simulator. Criterio vigente 0.11A: Sonnet judge por defecto y Opus solo para calibración explícita.
**Dependencias:** 0.2-0.7 mergeados (necesita adapters para mockear integraciones).
**Tiempo estimado:** 5-7 días.

**Archivos nuevos:**

- `supabase/migrations/20260522000004_add_simulator_tables.sql`:
  ```sql
  CREATE TABLE user_profiles (
      id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id       UUID,  -- NULL = template global
      name            TEXT NOT NULL,
      persona         JSONB NOT NULL,
      goal            TEXT,
      initial_message TEXT NOT NULL,
      follow_up_strategy TEXT,
      metadata        JSONB,
      created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );
  
  CREATE TABLE simulation_scenarios (
      id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id       UUID,
      aop_slug        TEXT NOT NULL,
      user_profile_id UUID NOT NULL REFERENCES user_profiles(id),
      expected_outcome TEXT,
      expected_skills JSONB,
      assertions      JSONB,
      is_active       BOOLEAN NOT NULL DEFAULT TRUE,
      created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );
  
  CREATE TABLE simulation_runs (
      id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id       UUID,
      scenario_id     UUID REFERENCES simulation_scenarios(id),
      aop_version     INT,
      status          TEXT NOT NULL,  -- 'running' | 'passed' | 'failed' | 'errored'
      transcript      JSONB,
      reasoning_events JSONB,
      judge_eval      JSONB,
      tokens_used     INT,
      cost_cents      NUMERIC,
      started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      completed_at    TIMESTAMPTZ
  );
  ```

- `apps/api/simulator/user_simulator.py`: LLM-bot que actúa como persona. Genera mensajes turno por turno según `goal` + `follow_up_strategy`.

- `apps/api/simulator/runner.py`: multi-turn loop. user_simulator ↔ agente real (corre el grafo completo). Termina cuando `goal_achieved` o `max_turns` o `give_up`.

- `apps/api/simulator/judge.py`: LLM-as-judge con 4 dimensiones (Reasoning, Knowledge, Tools, Brand voice). Reusa infra del slow agent Sprint 11 con prompt nuevo orientado a simulations.

- `apps/api/simulator/mocks.py`: helpers para mockear adapters durante simulation (ShopifyAdapter mock con respuestas predefinidas, etc).

- `apps/api/routers/simulations.py`: API REST + bulk run endpoint.

- `apps/web/app/(dashboard)/tenants/[tenantId]/simulator/page.tsx`: UI super_admin para correr scenarios + ver resultados.

**Componentes UI:**
- Lista de scenarios por AOP
- Botón "Run all"
- Resultados por dimension con scores + razones del judge
- Drill-down a un run con transcript turno por turno + reasoning events + judge feedback

**Criterio done:**
- 20+ scenarios manuales escritos para AOPs existentes (`default`, `consulta_envio`, returns)
- Bulk run de los 20+ scenarios completa
- Judge da feedback útil (no genérico)
- UI super_admin permite correr scenario individual y ver resultado
- Documentar cómo crear un scenario nuevo dentro de `docs/simulator-design.md` o en el README del módulo simulator. No existe una guía separada.

---

### Sub-PR 0.11 — Validación E2E sistema actual + fix bugs

**Cuándo:** Último sub-PR del Bloque 0.
**Modelo:** Sonnet.
**Dependencias:** 0.10 (simulator funcionando).
**Tiempo estimado:** 3-5 días (depende de bugs encontrados).

**Nota 2026-05-28:** esta versión de 0.11 quedó superada. El alcance activo es `0.11A — Agent Verification Staging` en `docs/progress.md`: LangSmith como fuente primaria, simulator con Sonnet judge por defecto y tope normal de `$5`, Shopify test store con órdenes reales y Chatwoot como primer helpdesk.

**Plan:**

1. Escribir scenarios end-to-end que cubran:
   - Flujo completo de un ticket Shopify con consulta_envio
   - Escalación cuando KB no tiene info
   - Skill L3 con human approval gate
   - Supervisor pattern (L3 con Opus)
   - Slow agent post-mortem sobre simulation
   - Rate limiting trigger
   - Budget gate trigger

2. Ejecutar batch completo y revisar resultados.

3. Documentar bugs encontrados.

4. Fixear los críticos. Documentar los no-críticos para backlog.

5. Re-ejecutar hasta que pass rate ≥ 80% en scenarios críticos.

**Criterio done:**
- Pass rate ≥ 80% en scenarios e2e críticos
- Bugs documentados (fixed o trackeados)
- Confianza para arrancar Bloque 1

---

## Diagrama de dependencias

```
0.1 (tenant_agent removal)
   ↓
0.2 (framework adapters base)  ← bloqueante de todo
   ↓
   ├─ 0.3 (Shopify refactor)
   ├─ 0.4 (Chatwoot refactor)
   ├─ 0.5 (Zendesk + OAuth)
   ├─ 0.6 (Gorgias nuevo + OAuth)
   └─ 0.7 (Postmark outbound)
   
0.8 (roles internos)  ← paralelo, depende solo de 0.1

0.9 (AOPs steps[])  ← independiente, medio día

0.10 (Simulator MVP) ← depende de 0.2-0.7 (necesita adapters para mockear)
   ↓
0.11 (Validación E2E)  ← último
```

**Sub-PRs paralelizables** (no bloquean entre sí): 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9.

**Sub-PRs bloqueantes**: 0.1 → 0.2 → resto → 0.10 → 0.11.

---

## Timing realista

Asumiendo trabajo solo (Kenny + Claude Code) con jornadas de 6-8h productivas:

```
Semana 1:
├─ Lun-Mar: 0.1 (tenant_agent removal)
├─ Mié-Vie: 0.2 (framework adapters base)

Semana 2:
├─ Lun-Mié: 0.3 (Shopify) + 0.4 (Chatwoot) en paralelo
├─ Jue-Vie: 0.7 (Postmark) + 0.8 (roles internos) + 0.9 (AOPs steps[])

Semana 3:
├─ Lun-Vie: 0.5 (Zendesk + OAuth) + 0.6 (Gorgias + OAuth) 
   (requieren OAuth apps registered externamente)

Semana 4:
├─ Lun-Vie: 0.10 (Simulator MVP) + 0.11 (Validación E2E)

Buffer: 3-5 días de imprevistos.
```

---

## Después de Bloque 0

Cuando Bloque 0 esté completo:
1. **Validación final**: simulator pasa 80%+ scenarios → confianza para vender
2. **Anuncio**: actualizar `progress.md` con Bloque 0 completo + arrancar Bloque 1
3. **Iniciar Bloque 1** (Sprint A) con Design Sprint primero

**Si en algún momento el simulator descubre que algo crítico está roto** (ej: Shopify integration tiene bug significativo), **PARAR** y fixearlo antes de seguir. Mejor descubrir bugs internamente que con cliente real.
