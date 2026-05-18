-- Sprint 9.3 — Audit log de skills con pseudonimización PII
-- Registra toda ejecución de skill (L1/L2/L3), éxitos y errores.
-- La tabla tenant_secrets guarda el salt PII por tenant; el hashing
-- ocurre en la app (Python), no en Postgres, para que el salt nunca
-- aparezca en query logs.

BEGIN;

-- ─── Salts PII por tenant ────────────────────────────────────────────────────
-- Una fila por tenant. Rotarlo invalida todos los pseudónimos históricos (GDPR).
CREATE TABLE tenant_secrets (
  tenant_id   uuid PRIMARY KEY REFERENCES tenants(id),
  pii_salt    text NOT NULL,  -- hex-encoded 32 bytes, generado en app
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- Seed: tenants existentes reciben un salt aleatorio generado en Postgres.
-- Los nuevos tenants reciben su salt cuando el AuditLogger lo necesita por
-- primera vez (upsert en queries.py).
INSERT INTO tenant_secrets (tenant_id, pii_salt)
SELECT
  id,
  replace(gen_random_uuid()::text, '-', '') || replace(gen_random_uuid()::text, '-', '')
FROM tenants
WHERE deleted_at IS NULL
ON CONFLICT DO NOTHING;

-- RLS: cada tenant solo ve su propio salt.
ALTER TABLE tenant_secrets ENABLE ROW LEVEL SECURITY;
CREATE POLICY "tenant isolation"
  ON tenant_secrets
  USING (tenant_id = public.current_tenant_id());

-- ─── Audit log de skills ──────────────────────────────────────────────────────
CREATE TABLE skill_audit_log (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id           uuid NOT NULL REFERENCES tenants(id),
  conversation_id     uuid NOT NULL REFERENCES conversations(id),
  aop_slug            text NOT NULL,
  aop_version         int  NOT NULL,
  skill_slug          text NOT NULL,
  skill_tier          text NOT NULL CHECK (skill_tier IN ('L1', 'L2', 'L3')),
  -- NULL para L1 (read-only no necesita idempotency)
  idempotency_key     uuid,
  -- Inputs con PII pseudonimizado; el hash del original para forense
  inputs_redacted     jsonb NOT NULL,
  outputs_redacted    jsonb,  -- NULL si falló
  inputs_hash         text NOT NULL,   -- sha256(canonical_json(inputs_raw))
  confidence          numeric(3, 2),   -- confianza del LLM al elegir la skill
  supervisor_verdict  text,            -- 'approve' | 'reject' | NULL
  status              text NOT NULL CHECK (status IN (
    'success',
    'failed',
    'rejected_by_supervisor',
    'rejected_by_permissions'
  )),
  error_message       text,
  latency_ms          int,
  langfuse_trace_id   text,
  created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_skill_audit_log_tenant_time
  ON skill_audit_log(tenant_id, created_at DESC);

CREATE INDEX idx_skill_audit_log_idempotency
  ON skill_audit_log(tenant_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;

CREATE INDEX idx_skill_audit_log_conversation
  ON skill_audit_log(tenant_id, conversation_id);

ALTER TABLE skill_audit_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY "tenant isolation"
  ON skill_audit_log
  USING (tenant_id = public.current_tenant_id());

COMMIT;
