-- Bloque 1, Sub-PR 1.5 — Reporte semanal automatizado
-- Genera borradores por tenant, cola de revision Auyan, aprobacion y envio posterior.

begin;

create type weekly_report_status as enum (
  'draft',
  'pending_review',
  'approved',
  'sent'
);

create table weekly_reports (
  id                   uuid primary key default gen_random_uuid(),
  tenant_id            uuid not null references tenants(id),
  week_start           date not null,
  week_end             date not null,
  status               weekly_report_status not null default 'draft',
  subject              text not null,
  recipient_email      text,
  metrics              jsonb not null default '{}'::jsonb,
  narrative            text not null default '',
  created_by           uuid references auth.users(id),
  approved_by          uuid references auth.users(id),
  approved_at          timestamptz,
  sent_by              uuid references auth.users(id),
  sent_at              timestamptz,
  postmark_message_id  text,
  send_error           text,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  deleted_at           timestamptz,
  constraint weekly_reports_valid_week check (week_end >= week_start),
  constraint weekly_reports_metrics_object check (jsonb_typeof(metrics) = 'object'),
  constraint weekly_reports_sent_requires_timestamp check (status <> 'sent' or sent_at is not null),
  unique (tenant_id, week_start)
);

create index idx_weekly_reports_tenant_created
  on weekly_reports(tenant_id, created_at desc)
  where deleted_at is null;

create index idx_weekly_reports_tenant_status
  on weekly_reports(tenant_id, status, week_start desc)
  where deleted_at is null;

create trigger trg_weekly_reports_updated_at
  before update on weekly_reports
  for each row execute function set_updated_at();

alter table weekly_reports enable row level security;

create policy "super_admin_all_weekly_reports" on weekly_reports
  using (is_super_admin())
  with check (is_super_admin());

create policy "tenant_admin_select_weekly_reports" on weekly_reports
  for select
  using (tenant_id = current_tenant_id());

commit;
