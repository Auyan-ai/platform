-- Auyan — Grants para roles de Supabase
-- RLS controla qué filas; los GRANT controlan si el rol puede tocar la tabla.
-- Sin esto, authenticated recibe "permission denied" antes de que RLS evalúe.
--
-- Política:
--   - anon          → sin acceso a tablas de negocio.
--   - authenticated → CRUD sobre todas las tablas; RLS gateará por tenant.
--   - service_role  → ya bypasea RLS y tiene todo por defecto en Supabase.

begin;

grant usage on schema public to authenticated;

grant select, insert, update, delete on
  tenants,
  users,
  end_customers,
  conversations,
  messages,
  escalations,
  knowledge_base_documents,
  knowledge_base_chunks,
  tenant_configurations,
  tenant_prompts
to authenticated;

grant execute on function
  public.current_tenant_id(),
  public.is_super_admin()
to authenticated;

-- Que tablas futuras en public hereden el mismo permiso por defecto.
alter default privileges in schema public
  grant select, insert, update, delete on tables to authenticated;

alter default privileges in schema public
  grant execute on functions to authenticated;

commit;
