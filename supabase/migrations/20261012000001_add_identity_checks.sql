-- ADR 0013 · PR-3: nivel `guest` (número de pedido + email o teléfono del pedido).
--
-- `identity_checks` guarda cada intento de verificación como invitado y, si coincidió, el
-- grant `guest` (válido hasta `valid_until`) de esa conversación. Es también el contador de
-- los límites contra enumeración: fallos por conversación y por tenant.
--
-- Ninguna columna guarda emails ni teléfonos en claro: `attempt_key` y `claim_hashes` son
-- HMAC con la sal del tenant y `contact_masked` solo deja ver iniciales.
--
-- Solo se persisten `granted`, `order_not_found` y `contact_mismatch`. El bloqueo por
-- conversación y la pausa del tenant se calculan contando fallos, así que no se escriben.

begin;

create table identity_checks (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references tenants(id),
  conversation_id  uuid not null,
  kind             text not null check (kind in ('guest', 'otp')),
  outcome          text not null check (outcome in ('granted', 'order_not_found', 'contact_mismatch')),
  method           text not null,
  order_id         bigint,
  claim_hashes     text[] not null default '{}',
  attempt_key      text not null,
  contact_masked   text,
  valid_until      timestamptz,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  deleted_at       timestamptz,
  foreign key (conversation_id, tenant_id) references conversations(id, tenant_id),
  constraint identity_checks_granted_has_order
    check (outcome <> 'granted' or (order_id is not null and valid_until is not null))
);

-- Cada par (pedido, contacto) se prueba una sola vez por conversación.
create unique index uq_identity_checks_attempt
  on identity_checks (tenant_id, conversation_id, attempt_key)
  where deleted_at is null;

-- Fallos recientes del tenant (pausa) y de la conversación (bloqueo).
create index idx_identity_checks_failures
  on identity_checks (tenant_id, created_at desc)
  where outcome in ('order_not_found', 'contact_mismatch') and deleted_at is null;

create index idx_identity_checks_conversation
  on identity_checks (tenant_id, conversation_id, created_at desc)
  where deleted_at is null;

create trigger trg_identity_checks_updated_at
  before update on identity_checks
  for each row execute function set_updated_at();

alter table identity_checks enable row level security;

create policy identity_checks_rw on identity_checks
  for all
  using (is_super_admin() or tenant_id = current_tenant_id())
  with check (is_super_admin() or tenant_id = current_tenant_id());

commit;
