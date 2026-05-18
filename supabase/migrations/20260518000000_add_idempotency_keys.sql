-- Sprint 9.1 — Idempotency keys para deduplicación de webhooks
-- Evita que reintentos del canal creen mensajes/escalaciones duplicadas.
-- TTL de 24 horas; un job de limpieza puede borrar filas expiradas periódicamente.

begin;

create table idempotency_keys (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants(id),
  key             text not null,
  request_path    text not null,
  status          text not null default 'pending'
                    check (status in ('pending', 'done')),
  response_status integer,
  response_body   jsonb,
  created_at      timestamptz not null default now(),
  expires_at      timestamptz not null default (now() + interval '24 hours'),
  deleted_at      timestamptz,

  -- Un par (tenant, key) es único mientras no esté soft-deleted.
  -- Permite reusar la misma key tras expiración/borrado.
  unique (tenant_id, key)
);

create index on idempotency_keys (tenant_id, key, expires_at)
  where deleted_at is null;

-- RLS: mismo patrón que el resto de tablas operativas.
alter table idempotency_keys enable row level security;

create policy "tenant isolation"
  on idempotency_keys
  using (tenant_id = public.current_tenant_id());

commit;
