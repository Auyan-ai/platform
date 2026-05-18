-- Sprint 10: tabla de aprobaciones humanas para skills L3.
-- Cuando human_approval_required=TRUE, el agente crea una pending_approval
-- en lugar de ejecutar la skill directamente. El agente humano aprueba o rechaza
-- desde el dashboard interno.

CREATE TABLE IF NOT EXISTS pending_approvals (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID        NOT NULL REFERENCES tenants(id),
    conversation_id   UUID        NOT NULL REFERENCES conversations(id),
    skill_slug        TEXT        NOT NULL,
    skill_tier        TEXT        NOT NULL,
    inputs_raw        JSONB       NOT NULL,
    inputs_redacted   JSONB       NOT NULL,
    aop_slug          TEXT        NOT NULL,
    aop_version       INT         NOT NULL,
    langfuse_trace_id TEXT,
    status            TEXT        NOT NULL DEFAULT 'pending'
                                  CHECK (status IN ('pending', 'approved', 'rejected')),
    reviewed_by       UUID        REFERENCES users(id),
    reviewed_at       TIMESTAMPTZ,
    review_comment    TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_pending_approvals_tenant_status
    ON pending_approvals (tenant_id, status)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_pending_approvals_conversation
    ON pending_approvals (tenant_id, conversation_id)
    WHERE deleted_at IS NULL;

CREATE TRIGGER set_pending_approvals_updated_at
    BEFORE UPDATE ON pending_approvals
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE pending_approvals ENABLE ROW LEVEL SECURITY;

CREATE POLICY "tenant_isolation" ON pending_approvals
    USING (tenant_id = public.current_tenant_id());
