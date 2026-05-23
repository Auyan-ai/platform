-- Elimina el rol tenant_agent del sistema.
-- Post-pivot (2026-05-22): el modelo BPO fue descartado. Ya no hay agentes humanos de Auyan
-- atendiendo tickets. El único rol de tenant es tenant_admin.
-- Los usuarios con tenant_agent pasan a tenant_admin sin pérdida de acceso.
--
-- Approach: deshabilitar RLS + dropear todas las dependencias del enum
-- (policy + check constraint) durante el cambio de tipo, luego restaurarlas.
-- Esto elimina cualquier evaluación implícita que pueda comparar text vs user_role.

BEGIN;

-- 0. Deshabilitar triggers de usuario por si hay algún hook Supabase oculto
--    que compare role implícitamente
SET LOCAL session_replication_role = 'replica';

-- 1. Deshabilitar RLS y dropear policy (la policy llama is_super_admin que
--    aunque no toca la columna role, su evaluación se reevalúa al cambiar tipo)
ALTER TABLE users DISABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS users_rw ON users;

-- 2. Dropear CHECK constraint que depende del enum
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_tenant_required;

-- 3. Migrar usuarios existentes (con cast explícito por si quedan tenant_agent)
UPDATE users
SET   role = 'tenant_admin'::user_role
WHERE role::text = 'tenant_agent';

-- 4. Dropear default y convertir columna a text
ALTER TABLE users ALTER COLUMN role DROP DEFAULT;
ALTER TABLE users ALTER COLUMN role TYPE text;

-- 5. Recrear el enum sin tenant_agent
DROP TYPE user_role;
CREATE TYPE user_role AS ENUM ('super_admin', 'tenant_admin');

-- 6. Convertir columna de vuelta al enum y restaurar default
ALTER TABLE users ALTER COLUMN role TYPE user_role USING role::user_role;
ALTER TABLE users ALTER COLUMN role SET DEFAULT 'tenant_admin';

-- 7. Restaurar CHECK constraint con el enum nuevo
ALTER TABLE users ADD CONSTRAINT users_tenant_required
    CHECK (role = 'super_admin' OR tenant_id IS NOT NULL);

-- 8. Restaurar RLS policy y habilitar RLS
CREATE POLICY users_rw ON users
    FOR ALL
    USING (is_super_admin() OR tenant_id = current_tenant_id())
    WITH CHECK (is_super_admin() OR tenant_id = current_tenant_id());

ALTER TABLE users ENABLE ROW LEVEL SECURITY;

COMMIT;
