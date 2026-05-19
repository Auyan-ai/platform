-- Uso diario por tenant: tokens consumidos, costo USD y request count.
-- Permite implementar gates de presupuesto pre-grafo y exponer métricas al tenant.
--
-- Una fila por (tenant_id, date). El UPSERT incrementa atómicamente.

CREATE TABLE IF NOT EXISTS tenant_usage_daily (
    id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid        NOT NULL REFERENCES tenants(id),
    date          date        NOT NULL DEFAULT CURRENT_DATE,
    tokens_in     bigint      NOT NULL DEFAULT 0,
    tokens_out    bigint      NOT NULL DEFAULT 0,
    cost_usd      numeric(12, 6) NOT NULL DEFAULT 0,
    request_count integer     NOT NULL DEFAULT 0,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    deleted_at    timestamptz,

    UNIQUE (tenant_id, date)
);

CREATE INDEX IF NOT EXISTS idx_tenant_usage_daily_tenant_date
    ON tenant_usage_daily (tenant_id, date DESC);

ALTER TABLE tenant_usage_daily ENABLE ROW LEVEL SECURITY;

-- Solo el backend (service role) accede a esta tabla.
CREATE POLICY "service_role_all" ON tenant_usage_daily
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

CREATE TRIGGER set_tenant_usage_daily_updated_at
    BEFORE UPDATE ON tenant_usage_daily
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();
