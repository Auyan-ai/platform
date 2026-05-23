-- Bloque 0, Sub-PR 0.2: tabla de integraciones por tenant con credentials cifrados.
-- Las credentials se cifran en Python con AES-256-GCM antes de persistir;
-- nunca se almacena texto plano en esta tabla.

CREATE TABLE tenant_integrations (
    id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             UUID        NOT NULL REFERENCES tenants(id),
    kind                  TEXT        NOT NULL,          -- 'helpdesk' | 'commerce' | 'channel' | 'llm'
    provider              TEXT        NOT NULL,          -- 'gorgias' | 'zendesk' | 'chatwoot' | 'shopify' | ...
    credentials_encrypted BYTEA       NOT NULL,          -- AES-256-GCM: nonce(12) || ciphertext
    config                JSONB       NOT NULL DEFAULT '{}',
    is_active             BOOLEAN     NOT NULL DEFAULT TRUE,
    is_primary_for_kind   BOOLEAN     NOT NULL DEFAULT FALSE,
    enabled_at            TIMESTAMPTZ,
    enabled_by            UUID,                          -- FK blanda a users(id)
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at            TIMESTAMPTZ,

    CONSTRAINT kind_valid CHECK (kind IN ('helpdesk', 'commerce', 'channel', 'llm'))
);

-- Un solo registro activo por (tenant, kind, provider).
CREATE UNIQUE INDEX tenant_integrations_unique_active
    ON tenant_integrations (tenant_id, kind, provider)
    WHERE deleted_at IS NULL;

-- Solo un primary activo por (tenant, kind).
CREATE UNIQUE INDEX tenant_integrations_unique_primary
    ON tenant_integrations (tenant_id, kind)
    WHERE deleted_at IS NULL AND is_primary_for_kind = TRUE;

-- Índice de lookup frecuente por kind.
CREATE INDEX tenant_integrations_kind_idx
    ON tenant_integrations (tenant_id, kind)
    WHERE deleted_at IS NULL AND is_active = TRUE;

-- updated_at automático.
CREATE TRIGGER set_tenant_integrations_updated_at
    BEFORE UPDATE ON tenant_integrations
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- RLS: cada tenant solo ve sus propias integraciones.
ALTER TABLE tenant_integrations ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_integrations_isolation ON tenant_integrations
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
