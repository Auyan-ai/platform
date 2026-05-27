-- Bloque 1, Sub-PR 1.2 — tenant_facts
-- Datos factuales editables directamente por el cliente (tenant_admin).
-- Ejemplos: horarios, teléfono, email, dirección, ventana de devoluciones.
-- NO va al RAG — se inyecta como contexto estructurado en el system prompt.
-- El schema de `data` es flexible (JSONB); e-commerce usa las claves documentadas abajo.
--
-- Claves estándar (e-commerce vertical #1):
--   business_hours     — "Lunes-Viernes 9:00-18:00"
--   support_email      — "hola@tienda.com"
--   support_phone      — "+34 910 123 456"
--   website_url        — "https://tienda.com"
--   return_window_days — 30  (número)
--   return_policy_url  — "https://tienda.com/devoluciones"
--   shipping_info      — "24-48h hábiles en Península"

begin;

create table tenant_facts (
  tenant_id      uuid primary key references tenants(id),
  data           jsonb not null default '{}',
  version        int not null default 1,
  last_edited_by uuid references auth.users(id),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create trigger trg_tenant_facts_updated_at
  before update on tenant_facts
  for each row execute function set_updated_at();

-- ─── RLS ────────────────────────────────────────────────────────────────────

alter table tenant_facts enable row level security;

-- super_admin: acceso total
create policy "super_admin_all_facts" on tenant_facts
  using (is_super_admin())
  with check (is_super_admin());

-- tenant_admin: lectura y escritura (el cliente edita sus datos)
create policy "tenant_admin_all_facts" on tenant_facts
  using (tenant_id = current_tenant_id())
  with check (tenant_id = current_tenant_id());

commit;
