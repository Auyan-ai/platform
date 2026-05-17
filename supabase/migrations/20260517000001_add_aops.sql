-- Auyan — Sprint 7: AOPs en DB
-- Tablas: aops, aop_versions, intent_classifier_runs
-- aop_versions es append-only (trigger bloquea UPDATE y DELETE).

begin;

-- ============================================================
-- aops — tabla principal (una fila por workspace activo por tenant+slug)
-- ============================================================
create table aops (
  id               uuid not null default gen_random_uuid(),
  tenant_id        uuid not null references tenants(id),
  slug             text not null,
  workspace        text not null default 'production',
  current_version  int  not null default 1,
  is_active        boolean not null default true,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  deleted_at       timestamptz,
  primary key (id),
  unique (id, tenant_id),
  unique (tenant_id, slug, workspace),
  constraint aops_workspace_values check (workspace in ('production', 'staging'))
);

create index idx_aops_tenant_active
  on aops(tenant_id, workspace)
  where is_active = true and deleted_at is null;

create trigger trg_aops_updated_at
  before update on aops
  for each row execute function set_updated_at();

-- ============================================================
-- aop_versions — historial inmutable (append-only)
-- Nunca se modifica ni borra: cada save crea una fila nueva.
-- aops.current_version apunta a la versión activa.
-- ============================================================
create table aop_versions (
  id                uuid primary key default gen_random_uuid(),
  aop_id            uuid not null references aops(id),
  tenant_id         uuid not null references tenants(id),
  version           int  not null,
  yaml_frontmatter  jsonb not null,
  body_markdown     text not null,
  raw_source        text not null,
  created_by        uuid references users(id),
  created_at        timestamptz not null default now(),
  unique (aop_id, version)
);

create index idx_aop_versions_aop
  on aop_versions(aop_id, version desc);
create index idx_aop_versions_tenant
  on aop_versions(tenant_id, created_at desc);

create or replace function public.aop_versions_immutable()
returns trigger
language plpgsql
as $$
begin
  raise exception 'aop_versions es append-only: UPDATE y DELETE no están permitidos';
end;
$$;

create trigger trg_aop_versions_immutable
  before update or delete on aop_versions
  for each row execute function aop_versions_immutable();

-- ============================================================
-- intent_classifier_runs — audit log del selector de AOP
-- human_correction se puede rellenar a posterior (desde el dashboard).
-- ============================================================
create table intent_classifier_runs (
  id                     uuid primary key default gen_random_uuid(),
  tenant_id              uuid not null references tenants(id),
  conversation_id        uuid not null,
  turn_number            int  not null,
  primary_slug           text not null,
  primary_confidence     numeric(3,2) not null,
  alternative_slug       text,
  alternative_confidence numeric(3,2),
  ambiguity_detected     boolean not null,
  was_reclassification   boolean not null,
  human_correction       text,
  created_at             timestamptz not null default now(),
  foreign key (conversation_id, tenant_id)
    references conversations(id, tenant_id)
);

create index idx_intent_runs_tenant_created
  on intent_classifier_runs(tenant_id, created_at desc);
create index idx_intent_runs_conversation
  on intent_classifier_runs(conversation_id);
create index idx_intent_runs_slug
  on intent_classifier_runs(tenant_id, primary_slug);

-- ============================================================
-- RLS
-- ============================================================
alter table aops                   enable row level security;
alter table aop_versions           enable row level security;
alter table intent_classifier_runs enable row level security;

create policy aops_rw on aops
  for all
  using (is_super_admin() or tenant_id = current_tenant_id())
  with check (is_super_admin() or tenant_id = current_tenant_id());

create policy aop_versions_rw on aop_versions
  for all
  using (is_super_admin() or tenant_id = current_tenant_id())
  with check (is_super_admin() or tenant_id = current_tenant_id());

create policy intent_runs_rw on intent_classifier_runs
  for all
  using (is_super_admin() or tenant_id = current_tenant_id())
  with check (is_super_admin() or tenant_id = current_tenant_id());

commit;
