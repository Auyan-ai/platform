-- ADR 0014: política de devoluciones y cambios de cada tenant.
--
-- Una fila por versión y solo inserciones: la vigente es la última versión, si no está
-- borrada (`deleted_at`). Cada fila guarda quién la escribió y el documento completo, así que la
-- tabla es también el historial de cambios. El documento lo valida el API con
-- `services/returns_policy.ReturnsPolicy` antes de insertar.
--
-- Solo el API escribe (valida con el modelo y pone autor y versión): `authenticated` y
-- `anon` no pueden insertar, actualizar ni borrar por PostgREST. El tenant lee las suyas.
-- Borrar en blando la última versión deja al tenant sin política; no reactiva la anterior.

begin;

create table tenant_returns_policies (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants(id),
  version         int not null check (version > 0),
  schema_version  int not null check (schema_version > 0),
  policy          jsonb not null,
  edited_by       uuid references auth.users(id) on delete set null,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  deleted_at      timestamptz,
  constraint tenant_returns_policies_policy_is_object check (jsonb_typeof(policy) = 'object')
);

-- Dos guardados concurrentes con la misma versión esperada: el segundo choca aquí. Sirve
-- también para leer la última versión.
create unique index uq_tenant_returns_policies_version
  on tenant_returns_policies (tenant_id, version);

create trigger trg_tenant_returns_policies_updated_at
  before update on tenant_returns_policies
  for each row execute function set_updated_at();

alter table tenant_returns_policies enable row level security;

create policy tenant_returns_policies_select on tenant_returns_policies
  for select
  using (is_super_admin() or tenant_id = current_tenant_id());

revoke insert, update, delete, truncate on tenant_returns_policies from anon, authenticated;

commit;
