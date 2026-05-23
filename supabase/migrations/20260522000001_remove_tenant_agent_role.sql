-- Elimina el rol tenant_agent del sistema.
-- Post-pivot (2026-05-22): el modelo BPO fue descartado. Ya no hay agentes humanos de Auyan
-- atendiendo tickets. El único rol de tenant es tenant_admin.
-- Los usuarios con tenant_agent pasan a tenant_admin sin pérdida de acceso.

-- 1. Migrar usuarios existentes.
--    Casteamos role a text en el WHERE para evitar que RLS (is_super_admin)
--    fuerce un text = user_role en evaluación.
UPDATE users
SET   role = 'tenant_admin'::user_role
WHERE role::text = 'tenant_agent';

-- 2. Drop CHECK constraint que depende del enum.
--    Sin esto, ALTER COLUMN TYPE text re-evalúa la constraint con role=text
--    pero 'super_admin' quedó bindeado al enum viejo → text = user_role error.
ALTER TABLE users DROP CONSTRAINT users_tenant_required;

-- 3. Convertir columna a text y dropear default
ALTER TABLE users ALTER COLUMN role DROP DEFAULT;
ALTER TABLE users ALTER COLUMN role TYPE text;

-- 4. Recrear el enum sin tenant_agent
DROP TYPE user_role;
CREATE TYPE user_role AS ENUM ('super_admin', 'tenant_admin');

-- 5. Convertir columna de vuelta al enum y restaurar default
ALTER TABLE users ALTER COLUMN role TYPE user_role USING role::user_role;
ALTER TABLE users ALTER COLUMN role SET DEFAULT 'tenant_admin';

-- 6. Recrear la CHECK constraint con el enum nuevo
ALTER TABLE users ADD CONSTRAINT users_tenant_required
    CHECK (role = 'super_admin' OR tenant_id IS NOT NULL);
