-- Auyan — ADR 0015 §7 / PR 3: cola de ingestas de la web de la tienda.
--
-- Cola con lease como `inbound_jobs`. Estados (máquina en services/site_ingestion/models.py):
-- queued → fetching → extracting → ready, o failed con failure_reason. `attempts` hace de token
-- del lease: el worker solo escribe si conserva el `attempts` con el que reclamó.
--
-- Orden de despliegue: aplicar ANTES del deploy del API (el API inserta
-- `tenant_knowledge_submissions.ingestion_id` y el worker sondea esta tabla).

begin;

create table site_ingestions (
  id                  uuid primary key default gen_random_uuid(),
  tenant_id           uuid not null references tenants(id),
  root_url            text not null,
  platform            text check (platform in ('shopify', 'other')),
  status              text not null default 'queued'
                        check (status in ('queued', 'fetching', 'extracting', 'ready', 'failed')),
  attempts            integer not null default 0,
  max_attempts        integer not null default 3,
  run_after           timestamptz not null default now(),
  locked_until        timestamptz,
  failure_reason      text,
  stats               jsonb not null default '{}'::jsonb,
  cost_usd            numeric(12, 6) not null default 0,
  langsmith_trace_id  text,
  requested_by        uuid references auth.users(id) on delete set null,
  started_at          timestamptz,
  finished_at         timestamptz,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  deleted_at          timestamptz,
  constraint site_ingestions_stats_is_object check (jsonb_typeof(stats) = 'object'),
  constraint site_ingestions_failed_has_reason
    check (status <> 'failed' or failure_reason is not null)
);

create unique index uq_site_ingestions_one_active_per_tenant
  on site_ingestions (tenant_id)
  where deleted_at is null and status in ('queued', 'fetching', 'extracting');

create index site_ingestions_claimable_idx
  on site_ingestions (created_at)
  where deleted_at is null and status in ('queued', 'fetching', 'extracting');

create trigger trg_site_ingestions_updated_at
  before update on site_ingestions
  for each row execute function set_updated_at();

alter table site_ingestions enable row level security;

create policy site_ingestions_super_admin_all on site_ingestions
  for all
  using (is_super_admin())
  with check (is_super_admin());

create policy site_ingestions_tenant_select on site_ingestions
  for select
  using (tenant_id = current_tenant_id());

alter table tenant_knowledge_submissions
  add column if not exists ingestion_id uuid references site_ingestions(id);

create index if not exists idx_tenant_knowledge_submissions_ingestion
  on tenant_knowledge_submissions (tenant_id, ingestion_id)
  where ingestion_id is not null and deleted_at is null;

comment on column tenant_knowledge_submissions.ingestion_id is
  'Ingesta de la web que creó la submission (ADR 0015 §3). NULL para las altas manuales.';

commit;
