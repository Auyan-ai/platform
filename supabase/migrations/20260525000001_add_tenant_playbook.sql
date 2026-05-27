-- Bloque 1, Sub-PR 1.1 — tenant_playbook
-- "Biblia" del cliente. Auyan la mantiene (qa_km / super_admin).
-- El cliente NO la edita (solo lectura para tenant_admin).
-- NO va al RAG — se inyecta como contexto estructurado en el system prompt.

begin;

create table tenant_playbook (
  tenant_id           uuid primary key references tenants(id),
  -- Cinco secciones fijas, todas markdown
  brand_voice         text not null default '',
  product_overview    text not null default '',
  policies            text not null default '',
  escalation_notes    text not null default '',
  agent_instructions  text not null default '',
  -- Control de versión simple (incrementa con cada upsert)
  version             int not null default 1,
  last_edited_by      uuid references auth.users(id),
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

create trigger trg_tenant_playbook_updated_at
  before update on tenant_playbook
  for each row execute function set_updated_at();

-- ─── RLS ────────────────────────────────────────────────────────────────────

alter table tenant_playbook enable row level security;

-- super_admin: acceso total (Auyan edita el playbook)
create policy "super_admin_all_playbook" on tenant_playbook
  using (is_super_admin())
  with check (is_super_admin());

-- tenant_admin: solo lectura (el cliente ve el playbook, no lo edita)
create policy "tenant_admin_select_playbook" on tenant_playbook
  for select
  using (tenant_id = current_tenant_id());

commit;
