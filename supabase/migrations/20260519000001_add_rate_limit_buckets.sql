-- Rate limiting: ventanas fijas de 60s por tenant y por end_customer.
-- La query de upsert es atómica — no hay race condition entre workers.
-- Cleanup: el job de limpieza borra filas con window_start < now() - 1h.

CREATE TABLE IF NOT EXISTS rate_limit_buckets (
    tenant_id    uuid        NOT NULL REFERENCES tenants(id),
    bucket_key   text        NOT NULL,  -- 'tenant' | 'customer:<uuid>'
    window_start timestamptz NOT NULL,  -- date_trunc('minute', now())
    count        integer     NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, bucket_key, window_start)
);

-- Índice para el cleanup job (borra filas expiradas por window_start)
CREATE INDEX IF NOT EXISTS rate_limit_buckets_window_start
    ON rate_limit_buckets (window_start);

-- RLS: el service role bypasea RLS; los clientes directos solo ven su tenant
ALTER TABLE rate_limit_buckets ENABLE ROW LEVEL SECURITY;

CREATE POLICY rate_limit_buckets_tenant_isolation ON rate_limit_buckets
    USING (tenant_id = (current_setting('app.tenant_id', true))::uuid);
