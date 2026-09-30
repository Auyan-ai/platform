-- Sprint 1 (s78) — Cola duradera de turnos inbound (#260) + serialización por conversación (A2 #2).
--
-- Los webhooks de helpdesk (Zendesk/Gorgias/Chatwoot) ya no corren el grafo dentro del
-- request: validan firma + idempotencia, persisten el mensaje inbound y encolan aquí un
-- job en la MISMA transacción, y responden 200 al instante. Un worker en proceso
-- (services/inbound_worker.py) reclama jobs con `FOR UPDATE` + advisory lock por
-- (tenant_id, conversation_id): nunca corren dos turnos a la vez sobre la misma
-- conversación. Sobrevive a reinicios de Cloud Run: un job `running` cuyo lease expiró
-- se vuelve a reclamar.
--
-- Estados:
--   pending    → esperando worker (o reintento con backoff: run_after en el futuro)
--   running    → reclamado; locked_until = lease (se renueva con heartbeat)
--   done       → turno completado (decision registrada)
--   failed     → agotó reintentos (se loguea como error y alerta)
--   superseded → absorbido por un mensaje posterior de la misma conversación: el turno
--                del mensaje más nuevo responde a la ráfaga completa (superseded_by)

begin;

create table inbound_jobs (
  id                 uuid primary key default gen_random_uuid(),
  tenant_id          uuid not null references tenants(id),
  conversation_id    uuid not null references conversations(id),
  inbound_message_id uuid not null references messages(id),
  end_customer_id    uuid not null references end_customers(id),
  -- Canal del inbound (zendesk/gorgias/chatwoot). La respuesta se entrega al
  -- `conversations.external_id` vía el adapter del helpdesk.
  channel            text not null,
  status             text not null default 'pending'
                       check (status in ('pending', 'running', 'done', 'failed', 'superseded')),
  attempts           integer not null default 0,
  max_attempts       integer not null default 3,
  run_after          timestamptz not null default now(),
  locked_until       timestamptz,
  superseded_by      uuid references inbound_jobs(id),
  decision           text,
  last_error         text,
  started_at         timestamptz,
  finished_at        timestamptz,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  deleted_at         timestamptz,

  -- Un mensaje inbound se encola una sola vez.
  unique (inbound_message_id)
);

-- Barrido del worker: jobs vivos por antigüedad.
create index inbound_jobs_claimable_idx
  on inbound_jobs (created_at)
  where deleted_at is null and status in ('pending', 'running');

-- Serialización por conversación: ¿hay un turno corriendo? / jobs a absorber.
create index inbound_jobs_conversation_idx
  on inbound_jobs (tenant_id, conversation_id, status)
  where deleted_at is null;

create trigger trg_inbound_jobs_updated_at
  before update on inbound_jobs
  for each row execute function set_updated_at();

-- RLS: mismo patrón que el resto de tablas operativas (el backend usa el rol postgres).
alter table inbound_jobs enable row level security;

create policy "tenant isolation"
  on inbound_jobs
  using (tenant_id = public.current_tenant_id());

commit;
