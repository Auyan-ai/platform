-- Sprint 10: tabla de permisos por skill por tenant.
-- Cada skill puede habilitarse/deshabilitarse por tenant, con opción de requerir
-- aprobación humana antes de ejecutar (obligatorio para L3 en el primer mes).

CREATE TABLE IF NOT EXISTS tenant_tool_permissions (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               UUID        NOT NULL REFERENCES tenants(id),
    skill_slug              TEXT        NOT NULL,
    is_enabled              BOOLEAN     NOT NULL DEFAULT FALSE,
    threshold_override      NUMERIC(3,2),
    human_approval_required BOOLEAN     NOT NULL DEFAULT FALSE,
    enabled_at              TIMESTAMPTZ,
    enabled_by              UUID        REFERENCES users(id),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at              TIMESTAMPTZ,
    UNIQUE (tenant_id, skill_slug)
);

CREATE INDEX IF NOT EXISTS idx_tool_perms_tenant
    ON tenant_tool_permissions (tenant_id)
    WHERE deleted_at IS NULL;

-- trigger updated_at
CREATE TRIGGER set_tool_permissions_updated_at
    BEFORE UPDATE ON tenant_tool_permissions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- RLS: tenant_admin/agent solo ven sus propias rows; super_admin ve todo.
ALTER TABLE tenant_tool_permissions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "tenant_isolation" ON tenant_tool_permissions
    USING (tenant_id = public.current_tenant_id());

-- Garantiza que el tenant de prueba Lunaria exista antes del seed de permisos
-- de abajo: en un entorno fresco (supabase start local) las migraciones corren
-- antes que supabase/seed.sql, así que sin esto el INSERT de más abajo rompe
-- por FK. Mismos valores fijos que usa seed.sql; ON CONFLICT lo hace idempotente
-- si seed.sql ya insertó el tenant primero (staging).
INSERT INTO tenants (id, slug, name, status)
VALUES (
    '11111111-1111-1111-1111-111111111111',
    'lunaria',
    'Lunaria — Ecommerce de joyería',
    'active'
)
ON CONFLICT (id) DO NOTHING;

-- Seed para el tenant de prueba Lunaria: L1 habilitadas, L2 deshabilitadas,
-- L3 deshabilitadas + human_approval_required=TRUE.
INSERT INTO tenant_tool_permissions (tenant_id, skill_slug, is_enabled, human_approval_required)
SELECT
    '11111111-1111-1111-1111-111111111111',
    slug,
    is_enabled,
    approval_required
FROM (VALUES
    ('shopify.get_order_by_email',      TRUE,  FALSE),
    ('shopify.get_order_status',        TRUE,  FALSE),
    ('shopify.get_product_info',        TRUE,  FALSE),
    ('shopify.get_customer_history',    TRUE,  FALSE),
    ('shopify.get_shop_policies',       TRUE,  FALSE),
    ('shopify.add_order_note',          FALSE, FALSE),
    ('shopify.tag_order',               FALSE, FALSE),
    ('shopify.update_shipping_address', FALSE, TRUE),
    ('shopify.cancel_order',            FALSE, TRUE),
    ('shopify.refund_partial',          FALSE, TRUE),
    ('shopify.start_return',            FALSE, TRUE)
) AS t(slug, is_enabled, approval_required)
ON CONFLICT (tenant_id, skill_slug) DO NOTHING;
