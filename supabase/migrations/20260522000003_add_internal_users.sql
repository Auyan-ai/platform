-- Sub-PR 0.8: Roles internos estructura DB
-- Tablas: internal_users, tenant_assignments, role_permissions
-- Separadas de public.users (clientes) — mismo Supabase Auth, distinto perfil de negocio.

-- ─── ENUM ────────────────────────────────────────────────────────────────────

CREATE TYPE internal_role AS ENUM (
    'super_admin',   -- Kenny + esposa. Acceso total cross-tenant.
    'aide',          -- AI Deployment Engineer. Scoped a tenants asignados.
    'qa_km',         -- QA + Knowledge Management. Transversal.
    'ops_manager',   -- Reportes + billing. Sin acceso técnico.
    'cs_manager'     -- Relación comercial. Solo lectura.
);

-- ─── TABLAS ──────────────────────────────────────────────────────────────────

CREATE TABLE internal_users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_user_id  UUID UNIQUE NOT NULL,  -- ref a auth.users (mismo Supabase Auth que users tabla cliente)
    name          TEXT NOT NULL,
    email         TEXT UNIQUE NOT NULL,
    role          internal_role NOT NULL DEFAULT 'aide',
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at    TIMESTAMPTZ
);

CREATE INDEX internal_users_auth_user_id_idx ON internal_users (auth_user_id) WHERE deleted_at IS NULL;
CREATE INDEX internal_users_role_idx ON internal_users (role) WHERE deleted_at IS NULL;

CREATE TABLE tenant_assignments (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL REFERENCES tenants(id),
    internal_user_id  UUID NOT NULL REFERENCES internal_users(id),
    role_in_tenant    TEXT NOT NULL,  -- 'aide_primary' | 'aide_backup' | 'qa_assigned' | etc
    assigned_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    assigned_by       UUID REFERENCES internal_users(id),
    unassigned_at     TIMESTAMPTZ
);

-- Solo una asignación activa por (tenant, usuario, rol)
CREATE UNIQUE INDEX tenant_assignments_active_idx
    ON tenant_assignments (tenant_id, internal_user_id, role_in_tenant)
    WHERE unassigned_at IS NULL;

CREATE INDEX tenant_assignments_tenant_idx ON tenant_assignments (tenant_id) WHERE unassigned_at IS NULL;
CREATE INDEX tenant_assignments_user_idx ON tenant_assignments (internal_user_id) WHERE unassigned_at IS NULL;

CREATE TABLE role_permissions (
    role        internal_role NOT NULL,
    permission  TEXT NOT NULL,
    PRIMARY KEY (role, permission)
);

-- ─── SEED PERMISOS ───────────────────────────────────────────────────────────
-- super_admin recibe todos los permisos explícitamente (auditable).
-- Ajustar vía INSERT/DELETE — no requiere migración de schema.

INSERT INTO role_permissions (role, permission) VALUES
    -- super_admin: todos
    ('super_admin', 'tenant.read.any'),
    ('super_admin', 'tenant.write.any'),
    ('super_admin', 'aop.read'),
    ('super_admin', 'aop.edit'),
    ('super_admin', 'kb.read'),
    ('super_admin', 'kb.write'),
    ('super_admin', 'integration.connect'),
    ('super_admin', 'integration.read'),
    ('super_admin', 'conversation.read'),
    ('super_admin', 'conversation.respond'),
    ('super_admin', 'approval.l2'),
    ('super_admin', 'approval.l3'),
    ('super_admin', 'proposal.review'),
    ('super_admin', 'report.generate'),
    ('super_admin', 'report.approve'),
    ('super_admin', 'billing.read'),
    ('super_admin', 'billing.write'),
    ('super_admin', 'internal_user.manage'),
    ('super_admin', 'tenant_assignment.manage'),
    ('super_admin', 'client.commercial'),

    -- aide: técnico, scoped a tenants asignados
    ('aide', 'aop.read'),
    ('aide', 'aop.edit'),
    ('aide', 'kb.read'),
    ('aide', 'kb.write'),
    ('aide', 'integration.connect'),
    ('aide', 'integration.read'),
    ('aide', 'conversation.read'),
    ('aide', 'conversation.respond'),
    ('aide', 'approval.l2'),
    ('aide', 'approval.l3'),
    ('aide', 'proposal.review'),
    ('aide', 'report.generate'),

    -- qa_km: transversal, sin acceso técnico-write ni billing
    ('qa_km', 'aop.read'),
    ('qa_km', 'kb.read'),
    ('qa_km', 'kb.write'),
    ('qa_km', 'integration.read'),
    ('qa_km', 'conversation.read'),
    ('qa_km', 'approval.l2'),
    ('qa_km', 'proposal.review'),
    ('qa_km', 'report.generate'),

    -- ops_manager: reportes + billing, sin técnico
    ('ops_manager', 'tenant.read.any'),
    ('ops_manager', 'integration.read'),
    ('ops_manager', 'conversation.read'),
    ('ops_manager', 'report.generate'),
    ('ops_manager', 'report.approve'),
    ('ops_manager', 'billing.read'),
    ('ops_manager', 'billing.write'),
    ('ops_manager', 'tenant_assignment.manage'),

    -- cs_manager: solo lectura comercial
    ('cs_manager', 'tenant.read.any'),
    ('cs_manager', 'integration.read'),
    ('cs_manager', 'conversation.read'),
    ('cs_manager', 'billing.read'),
    ('cs_manager', 'tenant_assignment.manage'),
    ('cs_manager', 'client.commercial');

-- ─── RLS ─────────────────────────────────────────────────────────────────────
-- Por ahora solo el service_role tiene acceso (misma política que otras tablas
-- sin tenant_id). En Bloque 1 se pueden agregar policies más granulares.

ALTER TABLE internal_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE role_permissions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_internal_users" ON internal_users
    FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "service_role_tenant_assignments" ON tenant_assignments
    FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "service_role_role_permissions" ON role_permissions
    FOR ALL TO service_role USING (true) WITH CHECK (true);
