-- Sprint 2 · PR-4: handoff modular al helpdesk del cliente (ADR 0010).
--
-- Un handoff es el período en que un HUMANO lleva la conversación de un canal de
-- mensajería (WhatsApp) y la IA calla:
--   - target 'helpdesk': ticket abierto en el helpdesk primario del tenant (Zendesk hoy);
--     el comprador sigue en WhatsApp y el equipo contesta desde el ticket.
--   - target 'device'  : la marca contestó desde la app de WhatsApp Business (coexistence);
--     la IA calla hasta `expires_at` (12 h sin actividad humana por defecto).
-- Registro auditable: motivo, apertura, última actividad humana, cierre y su motivo.

begin;

create table conversation_handoffs (
  id                  uuid primary key default gen_random_uuid(),
  tenant_id           uuid not null references tenants(id),
  conversation_id     uuid not null,
  target              text not null check (target in ('helpdesk', 'device')),
  helpdesk_provider   text,
  external_ticket_id  text,
  status              text not null default 'active' check (status in ('active', 'closed')),
  reason              text not null,
  opened_at           timestamptz not null default now(),
  last_human_at       timestamptz,
  expires_at          timestamptz,
  closed_at           timestamptz,
  closed_reason       text,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  deleted_at          timestamptz,
  foreign key (conversation_id, tenant_id) references conversations(id, tenant_id),
  constraint conversation_handoffs_helpdesk_has_ticket
    check (target <> 'helpdesk'
           or (helpdesk_provider is not null and external_ticket_id is not null)),
  constraint conversation_handoffs_device_expires
    check (target <> 'device' or expires_at is not null),
  constraint conversation_handoffs_closed_consistent
    check ((status = 'closed') = (closed_at is not null))
);

-- Un solo handoff activo por conversación.
create unique index uq_conversation_handoffs_active
  on conversation_handoffs (tenant_id, conversation_id)
  where status = 'active' and deleted_at is null;

-- Lookup desde el webhook del helpdesk (ticket → handoff).
create unique index uq_conversation_handoffs_ticket
  on conversation_handoffs (tenant_id, helpdesk_provider, external_ticket_id)
  where external_ticket_id is not null and deleted_at is null;

create index idx_conversation_handoffs_conversation
  on conversation_handoffs (tenant_id, conversation_id, created_at desc)
  where deleted_at is null;

create trigger trg_conversation_handoffs_updated_at
  before update on conversation_handoffs
  for each row execute function set_updated_at();

alter table conversation_handoffs enable row level security;

create policy conversation_handoffs_rw on conversation_handoffs
  for all
  using (is_super_admin() or tenant_id = current_tenant_id())
  with check (is_super_admin() or tenant_id = current_tenant_id());

commit;
