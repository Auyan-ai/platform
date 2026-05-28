-- Bloque 1, Sub-PR 1.4 — KB drop-zone + pending review
-- Intake de conocimiento aportado por cliente. Auyan revisa antes de indexar al RAG.

begin;

create type tenant_knowledge_source_type as enum ('text', 'url', 'file');
create type tenant_knowledge_submission_status as enum (
  'pending_review',
  'approved',
  'rejected'
);

create table tenant_knowledge_submissions (
  id                    uuid primary key default gen_random_uuid(),
  tenant_id             uuid not null references tenants(id),
  title                 text not null,
  source_type           tenant_knowledge_source_type not null,
  source_url            text,
  original_filename     text,
  content               text not null default '',
  notes                 text,
  status                tenant_knowledge_submission_status not null default 'pending_review',
  metadata              jsonb not null default '{}'::jsonb,
  submitted_by          uuid references auth.users(id),
  reviewed_by           uuid references auth.users(id),
  reviewed_at           timestamptz,
  review_note           text,
  processed_document_id uuid,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  deleted_at            timestamptz,
  constraint tenant_knowledge_submissions_metadata_object
    check (jsonb_typeof(metadata) = 'object'),
  constraint tenant_knowledge_submissions_content_or_url
    check (length(btrim(content)) > 0 or source_url is not null),
  foreign key (processed_document_id, tenant_id)
    references knowledge_base_documents(id, tenant_id)
);

create index idx_tenant_knowledge_submissions_tenant_status
  on tenant_knowledge_submissions(tenant_id, status, created_at desc)
  where deleted_at is null;

create index idx_tenant_knowledge_submissions_tenant_created
  on tenant_knowledge_submissions(tenant_id, created_at desc)
  where deleted_at is null;

create trigger trg_tenant_knowledge_submissions_updated_at
  before update on tenant_knowledge_submissions
  for each row execute function set_updated_at();

alter table tenant_knowledge_submissions enable row level security;

-- super_admin: acceso total para revisar y procesar submissions.
create policy "super_admin_all_knowledge_submissions" on tenant_knowledge_submissions
  using (is_super_admin())
  with check (is_super_admin());

-- tenant_admin: puede aportar y consultar sus propios submissions.
create policy "tenant_admin_select_knowledge_submissions" on tenant_knowledge_submissions
  for select
  using (tenant_id = current_tenant_id());

create policy "tenant_admin_insert_knowledge_submissions" on tenant_knowledge_submissions
  for insert
  with check (tenant_id = current_tenant_id());

commit;
