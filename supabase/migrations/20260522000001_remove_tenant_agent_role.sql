-- Elimina el rol tenant_agent del sistema.
-- Post-pivot (2026-05-22): el modelo BPO fue descartado. Ya no hay agentes humanos de Auyan
-- atendiendo tickets. El único rol de tenant es tenant_admin.
-- Los usuarios con tenant_agent pasan a tenant_admin sin pérdida de acceso.

-- 1. Migrar usuarios existentes
UPDATE users SET role = 'tenant_admin' WHERE role = 'tenant_agent';

-- 2. Recrear el enum sin tenant_agent
CREATE TYPE user_role_new AS ENUM ('super_admin', 'tenant_admin');

ALTER TABLE users ALTER COLUMN role DROP DEFAULT;
ALTER TABLE users
    ALTER COLUMN role TYPE user_role_new
    USING role::text::user_role_new;

DROP TYPE user_role;
ALTER TYPE user_role_new RENAME TO user_role;

ALTER TABLE users ALTER COLUMN role SET DEFAULT 'tenant_admin';
