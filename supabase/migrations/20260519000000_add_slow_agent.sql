-- Sprint 11: Slow Agent — runs, conversation judgments, improvement proposals.
-- El slow agent analiza conversaciones post-mortem y propone mejoras a los AOPs.
-- Tres tablas:
--   slow_agent_runs: un registro por ejecución del job.
--   conversation_judgments: qué conversaciones se juzgaron en cada run.
--   improvement_proposals: propuestas generadas por el judge.

BEGIN;

-- ─── Runs ─────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS slow_agent_runs (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               UUID        NOT NULL REFERENCES tenants(id),
    status                  TEXT        NOT NULL DEFAULT 'running'
                                        CHECK (status IN ('running', 'completed', 'failed')),
    conversations_evaluated INT         NOT NULL DEFAULT 0,
    proposals_generated     INT         NOT NULL DEFAULT 0,
    sonnet_tokens           INT         NOT NULL DEFAULT 0,
    opus_tokens             INT         NOT NULL DEFAULT 0,
    cost_usd                NUMERIC(10, 4),
    triggered_by            UUID        REFERENCES users(id),
    error                   TEXT,
    run_started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    run_ended_at            TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_slow_agent_runs_tenant
    ON slow_agent_runs (tenant_id, run_started_at DESC);

CREATE TRIGGER set_slow_agent_runs_updated_at
    BEFORE UPDATE ON slow_agent_runs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE slow_agent_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "tenant_isolation" ON slow_agent_runs
    USING (tenant_id = public.current_tenant_id());

-- ─── Conversation judgments ───────────────────────────────────────────────────
-- Una fila por (run, conversación). Permite re-correr el judge sobre la misma
-- conversación en runs distintos (si el prompt del judge cambia, por ejemplo).

CREATE TABLE IF NOT EXISTS conversation_judgments (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID        NOT NULL REFERENCES tenants(id),
    run_id              UUID        NOT NULL REFERENCES slow_agent_runs(id),
    conversation_id     UUID        NOT NULL REFERENCES conversations(id),
    verdict_summary     TEXT,
    proposal_id         UUID,       -- FK se agrega abajo tras crear improvement_proposals
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, conversation_id)
);

CREATE INDEX IF NOT EXISTS idx_conversation_judgments_tenant
    ON conversation_judgments (tenant_id, conversation_id);

ALTER TABLE conversation_judgments ENABLE ROW LEVEL SECURITY;
CREATE POLICY "tenant_isolation" ON conversation_judgments
    USING (tenant_id = public.current_tenant_id());

-- ─── Improvement proposals ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS improvement_proposals (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               UUID        NOT NULL REFERENCES tenants(id),
    run_id                  UUID        NOT NULL REFERENCES slow_agent_runs(id),
    proposal_type           TEXT        NOT NULL
                                        CHECK (proposal_type IN (
                                            'aop_edit', 'new_aop',
                                            'skill_request', 'guardrail_addition'
                                        )),
    aop_slug                TEXT,       -- NULL si new_aop o skill_request
    diff_markdown           TEXT        NOT NULL,
    rationale               TEXT        NOT NULL,
    evidence_conversations  UUID[]      NOT NULL DEFAULT '{}',
    judge_model_used        TEXT        NOT NULL,
    judge_confidence        NUMERIC(3, 2) NOT NULL,
    requires_eval_pass      BOOLEAN     NOT NULL DEFAULT TRUE,
    status                  TEXT        NOT NULL DEFAULT 'pending'
                                        CHECK (status IN (
                                            'pending', 'approved', 'rejected', 'applied'
                                        )),
    reviewed_by             UUID        REFERENCES users(id),
    reviewed_at             TIMESTAMPTZ,
    review_comment          TEXT,
    applied_version         INT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_improvement_proposals_tenant_status
    ON improvement_proposals (tenant_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_improvement_proposals_aop_slug
    ON improvement_proposals (tenant_id, aop_slug)
    WHERE aop_slug IS NOT NULL;

CREATE TRIGGER set_improvement_proposals_updated_at
    BEFORE UPDATE ON improvement_proposals
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE improvement_proposals ENABLE ROW LEVEL SECURITY;
CREATE POLICY "tenant_isolation" ON improvement_proposals
    USING (tenant_id = public.current_tenant_id());

-- FK diferida: apunta proposal_id en conversation_judgments a improvement_proposals
ALTER TABLE conversation_judgments
    ADD CONSTRAINT fk_judgment_proposal
    FOREIGN KEY (proposal_id) REFERENCES improvement_proposals(id);

COMMIT;
