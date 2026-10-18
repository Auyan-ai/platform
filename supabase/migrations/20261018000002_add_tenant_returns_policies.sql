-- ADR 0014: política de devoluciones y cambios de cada tenant.
--
-- Una fila por versión y solo inserciones: la vigente es la última versión sin
-- `deleted_at`. Cada fila guarda quién la escribió y el documento completo, así que la
-- tabla es también el historial de cambios. El documento lo valida el API con
-- `services/returns_policy.ReturnsPolicy` antes de insertar.
--
-- El cliente (tenant_admin) lee e inserta las suyas. Solo super_admin actualiza (soft
-- delete). Nadie borra.

begin;

create table tenant_returns_policies (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants(id),
  version         int not null check (version > 0),
  schema_version  int not null check (schema_version > 0),
  policy          jsonb not null,
  edited_by       uuid references auth.users(id),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  deleted_at      timestamptz,
  constraint tenant_returns_policies_policy_is_object check (jsonb_typeof(policy) = 'object')
);

-- Dos guardados concurrentes con la misma versión esperada: el segundo choca aquí.
create unique index uq_tenant_returns_policies_version
  on tenant_returns_policies (tenant_id, version);

create index idx_tenant_returns_policies_current
  on tenant_returns_policies (tenant_id, version desc)
  where deleted_at is null;

create trigger trg_tenant_returns_policies_updated_at
  before update on tenant_returns_policies
  for each row execute function set_updated_at();

alter table tenant_returns_policies enable row level security;

create policy tenant_returns_policies_select on tenant_returns_policies
  for select
  using (is_super_admin() or tenant_id = current_tenant_id());

create policy tenant_returns_policies_insert on tenant_returns_policies
  for insert
  with check (is_super_admin() or tenant_id = current_tenant_id());

create policy tenant_returns_policies_update on tenant_returns_policies
  for update
  using (is_super_admin())
  with check (is_super_admin());

commit;
