-- Elimina el rol tenant_agent del sistema.
-- Post-pivot (2026-05-22): el modelo BPO fue descartado. Ya no hay agentes humanos de Auyan
-- atendiendo tickets. El único rol de tenant es tenant_admin.
-- Los usuarios con tenant_agent pasan a tenant_admin sin pérdida de acceso.

-- 1. Migrar usuarios existentes
UPDATE users SET role = 'tenant_admin' WHERE role = 'tenant_agent';

-- 2. Pasar la columna a text para poder hacer DROP TYPE sin conflicto
ALTER TABLE users ALTER COLUMN role DROP DEFAULT;
ALTER TABLE users ALTER COLUMN role TYPE text;

-- 3. Eliminar el enum viejo y crear el nuevo con el mismo nombre
DROP TYPE user_role;
CREATE TYPE user_role AS ENUM ('super_admin', 'tenant_admin');

-- 4. Reconvertir la columna al nuevo enum y restaurar el default
ALTER TABLE users ALTER COLUMN role TYPE user_role USING role::user_role;
ALTER TABLE users ALTER COLUMN role SET DEFAULT 'tenant_admin';
