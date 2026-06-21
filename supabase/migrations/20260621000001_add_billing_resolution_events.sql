-- Billing Bloque 2 — log de eventos de resolución + suscripción por tenant.
-- PRD: docs/billing-resolution-prd.md (§2.2 conteo por evento, §2.3 ventana de
-- reapertura, §4 tiers). La unidad de cobro es la RESOLUCIÓN (el agente cerró sin
-- escalar). El log es append-only y billing-grade: cuenta por evento y permite
-- revertir reaperturas a través de periodos sin perder histórico, en vez de
-- depender solo de conversations.resolved_at (que es estado operativo).
--
-- Stripe (suscripción = suelo, metered = overage) se conecta DESPUÉS: los campos
-- stripe_* nacen nullable para que el cableado sea aditivo (ver PRD §7.2).

begin;

-- ─── resolution_events: log append-only por resolución ──────────────────────────
-- Una fila por cada vez que el agente marca una conversación resolved. reverted_at
-- se anota si el cliente reabre el MISMO thread; el conteo de billing decide si esa
-- reapertura descuenta según la ventana (§2.3) — la fila nunca se borra.

create table resolution_events (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants(id),
  conversation_id uuid not null references conversations(id),
  resolved_at     timestamptz not null default now(),
  reverted_at     timestamptz,
  created_at      timestamptz not null default now()
);

-- Conteo de resoluciones por tenant/periodo (la query de billing filtra por rango
-- de resolved_at y evalúa la ventana de reapertura sobre reverted_at).
create index idx_resolution_events_tenant_period
  on resolution_events (tenant_id, resolved_at);

-- Encontrar el evento abierto (no revertido) más reciente de una conversación al
-- reabrir.
create index idx_resolution_events_open_by_conversation
  on resolution_events (tenant_id, conversation_id, resolved_at desc)
  where reverted_at is null;

-- ─── billing_subscriptions: plan por tenant (snapshot de los parámetros) ─────────
-- Snapshot de floor/included/overage para que cambiar el catálogo de tiers NO altere
-- contratos vigentes. reopen_window_days y period_anchor_day parametrizan el conteo
-- (§2.3 / §6). Founding Partner = tier 'founding' con su rampa propia (per-cliente).

create table billing_subscriptions (
  tenant_id              uuid primary key references tenants(id),
  tier                   text not null
                           check (tier in ('starter', 'growth', 'scale', 'founding')),
  floor_cents            int not null check (floor_cents >= 0),
  included_resolutions   int not null check (included_resolutions >= 0),
  overage_cents          int not null check (overage_cents >= 0),
  currency               text not null default 'EUR',
  reopen_window_days     int not null default 7 check (reopen_window_days >= 0),
  period_anchor_day      int not null default 1
                           check (period_anchor_day between 1 and 31),
  status                 text not null default 'active'
                           check (status in ('active', 'paused', 'canceled')),
  stripe_customer_id     text,
  stripe_subscription_id text,
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now()
);

create trigger trg_billing_subscriptions_updated_at
  before update on billing_subscriptions
  for each row execute function set_updated_at();

-- ─── RLS ────────────────────────────────────────────────────────────────────────
-- El backend se conecta como `postgres` (bypasea RLS) y filtra por tenant_id en
-- cada query; estas políticas son la segunda capa (acceso directo / SECURITY
-- DEFINER). Para billing endurecemos: el cliente solo LEE — nunca falsea eventos ni
-- edita su propio plan. Los eventos los inserta el agente (rol postgres).

alter table resolution_events enable row level security;

create policy "super_admin_all_resolution_events" on resolution_events
  using (is_super_admin())
  with check (is_super_admin());

create policy "tenant_admin_read_resolution_events" on resolution_events
  for select
  using (tenant_id = current_tenant_id());

alter table billing_subscriptions enable row level security;

create policy "super_admin_all_billing_subscriptions" on billing_subscriptions
  using (is_super_admin())
  with check (is_super_admin());

create policy "tenant_admin_read_billing_subscriptions" on billing_subscriptions
  for select
  using (tenant_id = current_tenant_id());

commit;
