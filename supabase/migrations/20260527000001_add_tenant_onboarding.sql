-- Bloque 1, Sub-PR 1.3 — onboarding wizard + lifecycle
-- Wizard self-serve de 9 pasos para tenant_admin y estado operativo del agente.

begin;

create type agent_lifecycle_state as enum (
  'initial',
  'discovery',
  'building',
  'shadow',
  'ramping',
  'active',
  'paused',
  'churned'
);

alter table tenants
  add column agent_lifecycle_state agent_lifecycle_state not null default 'initial';

create table tenant_onboarding (
  tenant_id       uuid primary key references tenants(id),
  current_step    int not null default 1 check (current_step between 1 and 9),
  completed_steps jsonb not null default '[]',
  step_data       jsonb not null default '{}',
  submitted_at    timestamptz,
  completed_at    timestamptz,
  last_edited_by  uuid references auth.users(id),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  constraint tenant_onboarding_completed_steps_array
    check (jsonb_typeof(completed_steps) = 'array'),
  constraint tenant_onboarding_step_data_object
    check (jsonb_typeof(step_data) = 'object')
);

create trigger trg_tenant_onboarding_updated_at
  before update on tenant_onboarding
  for each row execute function set_updated_at();

alter table tenant_onboarding enable row level security;

-- super_admin: acceso total para operar onboarding por cualquier tenant.
create policy "super_admin_all_onboarding" on tenant_onboarding
  using (is_super_admin())
  with check (is_super_admin());

-- tenant_admin: lectura y escritura solo de su tenant.
create policy "tenant_admin_all_onboarding" on tenant_onboarding
  using (tenant_id = current_tenant_id())
  with check (tenant_id = current_tenant_id());

commit;
