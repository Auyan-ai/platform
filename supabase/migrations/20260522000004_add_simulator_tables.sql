-- Bloque 0, Sub-PR 0.10: Simulator MVP.
-- Corre el grafo real contra conversaciones sintéticas para validar AOPs y detectar regresiones.
-- Tres tablas:
--   user_profiles:        persona del cliente sintético (goal, initial_message, persona).
--   simulation_scenarios: AOP slug + perfil + expected_outcome + mock_fixtures + assertions.
--   simulation_runs:      resultado de correr un scenario (transcript, judge_eval, status).
-- Más una columna is_simulation en conversations para distinguir conversaciones sintéticas.

BEGIN;

-- ─── Marca de conversación sintética ──────────────────────────────────────────
-- CRÍTICO: el slow_agent y todas las queries operacionales deben filtrar
-- WHERE is_simulation = FALSE para no procesar conversaciones de simulación.

ALTER TABLE conversations ADD COLUMN is_simulation BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX conversations_not_simulation
    ON conversations (tenant_id, created_at)
    WHERE is_simulation = FALSE AND deleted_at IS NULL;

-- ─── user_profiles ────────────────────────────────────────────────────────────

CREATE TABLE user_profiles (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id),
    name            TEXT        NOT NULL,
    persona         JSONB       NOT NULL DEFAULT '{}',   -- tone, behavior, give_up_after
    goal            TEXT        NOT NULL,
    initial_message TEXT        NOT NULL,
    language        TEXT        NOT NULL DEFAULT 'es',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);

CREATE INDEX user_profiles_tenant_idx
    ON user_profiles (tenant_id)
    WHERE deleted_at IS NULL;

CREATE TRIGGER set_user_profiles_updated_at
    BEFORE UPDATE ON user_profiles
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "tenant_isolation" ON user_profiles
    USING (is_super_admin() OR tenant_id = current_tenant_id());

-- ─── simulation_scenarios ─────────────────────────────────────────────────────

CREATE TABLE simulation_scenarios (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID        NOT NULL REFERENCES tenants(id),
    name             TEXT        NOT NULL,
    description      TEXT,
    aop_slug         TEXT        NOT NULL,
    user_profile_id  UUID        NOT NULL REFERENCES user_profiles(id),
    expected_outcome TEXT        NOT NULL,
    mock_fixtures    JSONB       NOT NULL DEFAULT '{}',
    assertions       JSONB       NOT NULL DEFAULT '{}',
    max_turns        INT         NOT NULL DEFAULT 8,
    is_active        BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at       TIMESTAMPTZ
);

CREATE INDEX sim_scenarios_aop_slug
    ON simulation_scenarios (tenant_id, aop_slug)
    WHERE is_active = TRUE AND deleted_at IS NULL;

CREATE TRIGGER set_simulation_scenarios_updated_at
    BEFORE UPDATE ON simulation_scenarios
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE simulation_scenarios ENABLE ROW LEVEL SECURITY;
CREATE POLICY "tenant_isolation" ON simulation_scenarios
    USING (is_super_admin() OR tenant_id = current_tenant_id());

-- ─── simulation_runs ──────────────────────────────────────────────────────────
-- Append-only: un run es histórico inmutable (status pasa running → terminal).
-- Sin deleted_at (igual que slow_agent_runs).

CREATE TABLE simulation_runs (
    id                 UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          UUID          NOT NULL REFERENCES tenants(id),
    scenario_id        UUID          REFERENCES simulation_scenarios(id),
    aop_slug           TEXT          NOT NULL,
    aop_version        INT,
    conversation_id    UUID,                         -- la sintética en conversations
    batch_id           UUID,                         -- agrupa runs de un bulk run
    status             TEXT          NOT NULL DEFAULT 'running'
                                     CHECK (status IN (
                                         'running', 'passed', 'partial', 'failed', 'errored'
                                     )),
    termination_reason TEXT,                         -- goal_achieved | max_turns | give_up |
                                                     -- escalated_by_agent | agent_loop_detected | error
    turns_count        INT,
    transcript         JSONB,
    judge_eval         JSONB,
    assertions_results JSONB,
    assertions_passed  INT,
    assertions_total   INT,
    triggered_by       UUID,
    tokens_simulator   INT           NOT NULL DEFAULT 0,
    tokens_agent       INT           NOT NULL DEFAULT 0,
    tokens_judge       INT           NOT NULL DEFAULT 0,
    cost_cents         NUMERIC(10, 4),
    started_at         TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    completed_at       TIMESTAMPTZ,
    updated_at         TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX sim_runs_scenario
    ON simulation_runs (scenario_id, started_at DESC);

CREATE INDEX sim_runs_batch
    ON simulation_runs (batch_id)
    WHERE batch_id IS NOT NULL;

CREATE INDEX sim_runs_running
    ON simulation_runs (status)
    WHERE status = 'running';

-- Sirve a la query de cost cap diario por tenant.
CREATE INDEX sim_runs_tenant_daily_cost
    ON simulation_runs (tenant_id, started_at)
    WHERE status IN ('passed', 'partial', 'failed', 'errored');

CREATE TRIGGER set_simulation_runs_updated_at
    BEFORE UPDATE ON simulation_runs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE simulation_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "tenant_isolation" ON simulation_runs
    USING (is_super_admin() OR tenant_id = current_tenant_id());

COMMIT;
