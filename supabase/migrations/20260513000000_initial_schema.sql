-- Auyan — Migración inicial
-- Multi-tenant estricto con RLS, soft delete, observabilidad, pgvector
-- Convenciones:
--   - tenant_id NOT NULL en todas las tablas operativas
--   - deleted_at para soft delete (la app filtra; las policies no, para permitir restore)
--   - updated_at auto vía trigger
--   - FKs compuestas (id, tenant_id) para impedir cross-tenant incluso con service-role

begin;

-- ============================================================
-- Extensiones
-- ============================================================
create extension if not exists pgcrypto;
create extension if not exists vector;

-- ============================================================
-- Enums
-- ============================================================
create type user_role as enum ('super_admin', 'tenant_admin', 'tenant_agent');
create type channel_type as enum (
  'email', 'chat', 'widget', 'whatsapp', 'instagram',
  'zendesk', 'intercom', 'chatwoot'
);
create type conversation_status as enum (
  'open', 'pending', 'resolved', 'escalated', 'closed'
);
create type message_role as enum ('customer', 'agent_ai', 'agent_human', 'system');
create type message_direction as enum ('inbound', 'outbound');
create type escalation_status as enum ('pending', 'claimed', 'resolved');

-- ============================================================
-- Helpers de tenancy y auditoría
-- ============================================================

-- Lee tenant_id del JWT, con fallback a GUC seteado por el backend (defensa en profundidad).
create or replace function public.current_tenant_id()
returns uuid
language sql stable
as $$
  select nullif(
    coalesce(
      current_setting('request.jwt.claims', true)::jsonb ->> 'tenant_id',
      current_setting('app.tenant_id', true)
    ),
    ''
  )::uuid;
$$;

create or replace function public.is_super_admin()
returns boolean
language sql stable
as $$
  select coalesce(
    (current_setting('request.jwt.claims', true)::jsonb ->> 'role') = 'super_admin',
    false
  );
$$;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- ============================================================
-- tenants
-- ============================================================
create table tenants (
  id          uuid primary key default gen_random_uuid(),
  slug        text not null unique,
  name        text not null,
  status      text not null default 'active',
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  deleted_at  timestamptz
);

create trigger trg_tenants_updated_at
  before update on tenants
  for each row execute function set_updated_at();

-- ============================================================
-- users (staff: agentes humanos y admins). Ligado a auth.users.
-- super_admin (Auyan interno) puede tener tenant_id NULL.
-- ============================================================
create table users (
  id          uuid primary key references auth.users(id) on delete cascade,
  tenant_id   uuid references tenants(id),
  email       text not null,
  full_name   text,
  role        user_role not null default 'tenant_agent',
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  deleted_at  timestamptz,
  constraint users_tenant_required
    check (role = 'super_admin' or tenant_id is not null),
  unique (id, tenant_id)
);

create index idx_users_tenant on users(tenant_id) where deleted_at is null;
create index idx_users_email  on users(lower(email)) where deleted_at is null;

create trigger trg_users_updated_at
  before update on users
  for each row execute function set_updated_at();

-- ============================================================
-- end_customers (clientes finales del tenant; no se loguean)
-- ============================================================
create table end_customers (
  id           uuid not null default gen_random_uuid(),
  tenant_id    uuid not null references tenants(id),
  email        text,
  phone        text,
  external_id  text,
  full_name    text,
  metadata     jsonb not null default '{}'::jsonb,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  deleted_at   timestamptz,
  primary key (id),
  unique (id, tenant_id)
);

create index idx_end_customers_tenant
  on end_customers(tenant_id, created_at desc) where deleted_at is null;
create unique index uq_end_customers_email
  on end_customers(tenant_id, lower(email))
  where email is not null and deleted_at is null;
create unique index uq_end_customers_external
  on end_customers(tenant_id, external_id)
  where external_id is not null and deleted_at is null;

create trigger trg_end_customers_updated_at
  before update on end_customers
  for each row execute function set_updated_at();

-- ============================================================
-- conversations
-- ============================================================
create table conversations (
  id                 uuid not null default gen_random_uuid(),
  tenant_id          uuid not null references tenants(id),
  end_customer_id    uuid not null,
  channel            channel_type not null,
  external_id        text,
  subject            text,
  status             conversation_status not null default 'open',
  assigned_user_id   uuid,
  last_message_at    timestamptz,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  deleted_at         timestamptz,
  primary key (id),
  unique (id, tenant_id),
  foreign key (end_customer_id, tenant_id)
    references end_customers(id, tenant_id),
  foreign key (assigned_user_id, tenant_id)
    references users(id, tenant_id)
);

create index idx_conversations_tenant_created
  on conversations(tenant_id, created_at desc) where deleted_at is null;
create index idx_conversations_tenant_status
  on conversations(tenant_id, status) where deleted_at is null;
create index idx_conversations_customer
  on conversations(end_customer_id);
create unique index uq_conversations_external
  on conversations(tenant_id, channel, external_id)
  where external_id is not null;

create trigger trg_conversations_updated_at
  before update on conversations
  for each row execute function set_updated_at();

-- ============================================================
-- messages
-- metadata guarda: langfuse_trace_id, model, prompt_tokens, completion_tokens,
-- cost_usd, channel-specific payload.
-- ============================================================
create table messages (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references tenants(id),
  conversation_id  uuid not null,
  role             message_role not null,
  direction        message_direction not null,
  author_user_id   uuid,
  content          text not null,
  attachments      jsonb not null default '[]'::jsonb,
  metadata         jsonb not null default '{}'::jsonb,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  deleted_at       timestamptz,
  foreign key (conversation_id, tenant_id)
    references conversations(id, tenant_id),
  foreign key (author_user_id, tenant_id)
    references users(id, tenant_id),
  constraint messages_human_has_author
    check (role <> 'agent_human' or author_user_id is not null)
);

create index idx_messages_conversation_created
  on messages(conversation_id, created_at);
create index idx_messages_tenant_created
  on messages(tenant_id, created_at desc) where deleted_at is null;

create trigger trg_messages_updated_at
  before update on messages
  for each row execute function set_updated_at();

-- ============================================================
-- escalations (histórico completo; una conversación puede escalar varias veces)
-- ============================================================
create table escalations (
  id                       uuid primary key default gen_random_uuid(),
  tenant_id                uuid not null references tenants(id),
  conversation_id          uuid not null,
  reason                   text not null,
  triggered_by_message_id  uuid references messages(id),
  status                   escalation_status not null default 'pending',
  assigned_user_id         uuid,
  claimed_at               timestamptz,
  resolved_at              timestamptz,
  resolution_notes         text,
  metadata                 jsonb not null default '{}'::jsonb,
  created_at               timestamptz not null default now(),
  updated_at               timestamptz not null default now(),
  deleted_at               timestamptz,
  foreign key (conversation_id, tenant_id)
    references conversations(id, tenant_id),
  foreign key (assigned_user_id, tenant_id)
    references users(id, tenant_id)
);

create index idx_escalations_tenant_created
  on escalations(tenant_id, created_at desc) where deleted_at is null;
create index idx_escalations_conversation
  on escalations(conversation_id);
create index idx_escalations_open
  on escalations(tenant_id, status) where status <> 'resolved';

create trigger trg_escalations_updated_at
  before update on escalations
  for each row execute function set_updated_at();

-- ============================================================
-- knowledge_base_documents + knowledge_base_chunks (pgvector, 1536)
-- ============================================================
create table knowledge_base_documents (
  id          uuid not null default gen_random_uuid(),
  tenant_id   uuid not null references tenants(id),
  title       text not null,
  source      text,
  content     text not null,
  metadata    jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  deleted_at  timestamptz,
  primary key (id),
  unique (id, tenant_id)
);

create index idx_kb_docs_tenant
  on knowledge_base_documents(tenant_id, created_at desc)
  where deleted_at is null;

create trigger trg_kb_docs_updated_at
  before update on knowledge_base_documents
  for each row execute function set_updated_at();

create table knowledge_base_chunks (
  id           uuid primary key default gen_random_uuid(),
  tenant_id    uuid not null references tenants(id),
  document_id  uuid not null,
  chunk_index  int not null,
  content      text not null,
  embedding    vector(1536) not null,
  token_count  int,
  created_at   timestamptz not null default now(),
  foreign key (document_id, tenant_id)
    references knowledge_base_documents(id, tenant_id) on delete cascade,
  unique (document_id, chunk_index)
);

create index idx_kb_chunks_tenant on knowledge_base_chunks(tenant_id);
create index idx_kb_chunks_document on knowledge_base_chunks(document_id);
-- HNSW para búsqueda por similitud coseno; rápido en lecturas, build cost moderado.
create index idx_kb_chunks_embedding
  on knowledge_base_chunks using hnsw (embedding vector_cosine_ops);

-- ============================================================
-- tenant_configurations (1:1)
-- ============================================================
create table tenant_configurations (
  tenant_id             uuid primary key references tenants(id) on delete cascade,
  agent_model           text not null default 'claude-sonnet-4-6',
  escalation_threshold  numeric(3,2) not null default 0.70,
  active_channels       channel_type[] not null default '{}'::channel_type[],
  branding              jsonb not null default '{}'::jsonb,
  extra                 jsonb not null default '{}'::jsonb,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  constraint escalation_threshold_range
    check (escalation_threshold >= 0 and escalation_threshold <= 1)
);

create trigger trg_tenant_configurations_updated_at
  before update on tenant_configurations
  for each row execute function set_updated_at();

-- ============================================================
-- tenant_prompts (versionados; un solo activo por (tenant, name))
-- ============================================================
create table tenant_prompts (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants(id),
  name        text not null,
  version     int  not null,
  content     text not null,
  is_active   boolean not null default false,
  created_by  uuid references users(id),
  created_at  timestamptz not null default now(),
  deleted_at  timestamptz
);

create unique index uq_tenant_prompts_version
  on tenant_prompts(tenant_id, name, version);
create unique index uq_tenant_prompts_active
  on tenant_prompts(tenant_id, name)
  where is_active = true and deleted_at is null;
create index idx_tenant_prompts_lookup
  on tenant_prompts(tenant_id, name, version desc);

-- ============================================================
-- RLS
-- super_admin bypasea; el resto sólo ve filas de su tenant.
-- ============================================================
alter table tenants                  enable row level security;
alter table users                    enable row level security;
alter table end_customers            enable row level security;
alter table conversations            enable row level security;
alter table messages                 enable row level security;
alter table escalations              enable row level security;
alter table knowledge_base_documents enable row level security;
alter table knowledge_base_chunks    enable row level security;
alter table tenant_configurations    enable row level security;
alter table tenant_prompts           enable row level security;

-- tenants: super_admin todo; usuarios ven sólo su propia fila.
create policy tenants_read on tenants
  for select using (is_super_admin() or id = current_tenant_id());
create policy tenants_write on tenants
  for all using (is_super_admin()) with check (is_super_admin());

-- users: super_admin todo; staff ve su tenant.
create policy users_rw on users
  for all
  using (is_super_admin() or tenant_id = current_tenant_id())
  with check (is_super_admin() or tenant_id = current_tenant_id());

create policy end_customers_rw on end_customers
  for all
  using (is_super_admin() or tenant_id = current_tenant_id())
  with check (is_super_admin() or tenant_id = current_tenant_id());

create policy conversations_rw on conversations
  for all
  using (is_super_admin() or tenant_id = current_tenant_id())
  with check (is_super_admin() or tenant_id = current_tenant_id());

create policy messages_rw on messages
  for all
  using (is_super_admin() or tenant_id = current_tenant_id())
  with check (is_super_admin() or tenant_id = current_tenant_id());

create policy escalations_rw on escalations
  for all
  using (is_super_admin() or tenant_id = current_tenant_id())
  with check (is_super_admin() or tenant_id = current_tenant_id());

create policy kb_docs_rw on knowledge_base_documents
  for all
  using (is_super_admin() or tenant_id = current_tenant_id())
  with check (is_super_admin() or tenant_id = current_tenant_id());

create policy kb_chunks_rw on knowledge_base_chunks
  for all
  using (is_super_admin() or tenant_id = current_tenant_id())
  with check (is_super_admin() or tenant_id = current_tenant_id());

create policy tenant_configurations_rw on tenant_configurations
  for all
  using (is_super_admin() or tenant_id = current_tenant_id())
  with check (is_super_admin() or tenant_id = current_tenant_id());

create policy tenant_prompts_rw on tenant_prompts
  for all
  using (is_super_admin() or tenant_id = current_tenant_id())
  with check (is_super_admin() or tenant_id = current_tenant_id());

commit;
