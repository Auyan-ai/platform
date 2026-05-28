-- Bloque 1, Sub-PR 1.9 — Email outbound general
-- Templates editables y cola persistente para emails Auyan -> cliente.

begin;

create type outbound_email_job_status as enum (
  'queued',
  'sending',
  'sent',
  'failed',
  'canceled'
);

create table outbound_email_templates (
  id                 uuid primary key default gen_random_uuid(),
  tenant_id          uuid not null references tenants(id),
  key                text not null,
  name               text not null,
  subject_template   text not null,
  text_body_template text not null,
  html_body_template text,
  variables          jsonb not null default '[]'::jsonb,
  is_active          boolean not null default true,
  version            integer not null default 1,
  created_by         uuid references auth.users(id),
  updated_by         uuid references auth.users(id),
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  deleted_at         timestamptz,
  constraint outbound_email_templates_key_not_blank check (length(trim(key)) > 0),
  constraint outbound_email_templates_variables_array check (jsonb_typeof(variables) = 'array')
);

create unique index uniq_outbound_email_templates_tenant_key
  on outbound_email_templates(tenant_id, key)
  where deleted_at is null;

create index idx_outbound_email_templates_tenant_active
  on outbound_email_templates(tenant_id, is_active, updated_at desc)
  where deleted_at is null;

create table outbound_email_jobs (
  id                   uuid primary key default gen_random_uuid(),
  tenant_id            uuid not null references tenants(id),
  template_id          uuid references outbound_email_templates(id),
  recipient_email      text not null,
  subject              text not null,
  text_body            text not null,
  html_body            text,
  tag                  text,
  payload              jsonb not null default '{}'::jsonb,
  status               outbound_email_job_status not null default 'queued',
  attempts             integer not null default 0,
  max_attempts         integer not null default 3,
  next_attempt_at      timestamptz not null default now(),
  last_attempt_at      timestamptz,
  sent_at              timestamptz,
  postmark_message_id  text,
  error                text,
  requested_by         uuid references auth.users(id),
  idempotency_key      text,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  deleted_at           timestamptz,
  constraint outbound_email_jobs_payload_object check (jsonb_typeof(payload) = 'object'),
  constraint outbound_email_jobs_attempts_nonnegative check (attempts >= 0),
  constraint outbound_email_jobs_max_attempts_positive check (max_attempts > 0),
  constraint outbound_email_jobs_sent_requires_timestamp check (status <> 'sent' or sent_at is not null)
);

create unique index uniq_outbound_email_jobs_tenant_idempotency
  on outbound_email_jobs(tenant_id, idempotency_key)
  where idempotency_key is not null and deleted_at is null;

create index idx_outbound_email_jobs_dispatch
  on outbound_email_jobs(status, next_attempt_at, created_at)
  where deleted_at is null;

create index idx_outbound_email_jobs_tenant_status
  on outbound_email_jobs(tenant_id, status, created_at desc)
  where deleted_at is null;

create trigger trg_outbound_email_templates_updated_at
  before update on outbound_email_templates
  for each row execute function set_updated_at();

create trigger trg_outbound_email_jobs_updated_at
  before update on outbound_email_jobs
  for each row execute function set_updated_at();

alter table outbound_email_templates enable row level security;
alter table outbound_email_jobs enable row level security;

create policy "super_admin_all_outbound_email_templates" on outbound_email_templates
  using (is_super_admin())
  with check (is_super_admin());

create policy "tenant_admin_select_outbound_email_templates" on outbound_email_templates
  for select
  using (tenant_id = current_tenant_id());

create policy "super_admin_all_outbound_email_jobs" on outbound_email_jobs
  using (is_super_admin())
  with check (is_super_admin());

create policy "tenant_admin_select_outbound_email_jobs" on outbound_email_jobs
  for select
  using (tenant_id = current_tenant_id());

commit;
