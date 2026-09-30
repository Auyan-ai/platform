# ADR 0008 — Turnos inbound en una cola Postgres, serializados por conversación

**Estado:** Aceptada
**Fecha:** 2026-09-30 (sesión 78, issue #260 + A2 #2)

## Contexto

Los webhooks de helpdesk (Zendesk, Gorgias, Chatwoot) corrían el grafo completo
**dentro del request**. En el E2E en vivo de Zendesk (s77) un turno con supervisor y
reintentos tardó ~28 s. Zendesk corta a ~10–12 s y reintentó tres veces. La
idempotencia evitó el doble procesamiento, pero cada timeout cuenta como fallo del
webhook, y si se acumulan Zendesk lo desactiva. Gorgias y Chatwoot tienen límites
parecidos.

Además:

- Dos mensajes casi simultáneos del mismo cliente corrían **dos turnos en paralelo**
  sobre la misma conversación: historial cruzado, respuestas duplicadas y carreras
  en escalados y resoluciones.
- La key de idempotencia se reclamaba como `pending` en una conexión aparte. Si el
  proceso fallaba, se hacía soft-delete, pero el `unique (tenant_id, key)` no se
  libera con soft-delete, así que los reintentos del proveedor quedaban en `409
  in_flight` para siempre.
- La API corre en Cloud Run con `min-instances=0`, `max-instances=1` y
  `--no-cpu-throttling`. Cualquier trabajo en segundo plano debe sobrevivir a que la
  instancia se apague o se reinicie.

## Decisión

**El webhook solo valida, persiste y encola. El grafo corre en un worker que consume
una cola duradera en Postgres (`inbound_jobs`), y nunca hay dos turnos a la vez sobre
la misma conversación.**

- **Intake en una sola transacción** (`services/inbound_intake.py`): se reclama la
  key de idempotencia con `INSERT … ON CONFLICT DO NOTHING`, se hace upsert del
  cliente y la conversación, se inserta el mensaje y se encola el job. Si cae, no
  queda nada y el reintento reprocesa limpio. Un reintento concurrente espera a la
  transacción original y sale como duplicado. Después se responde 200.
- **Worker en proceso** (`services/inbound_worker.py`): N slots arrancados en el
  lifespan. Los despierta `notify()` al encolar y además sondean cada 5 s. Al
  arrancar, la instancia recoge los jobs pendientes o huérfanos.
- **Claim serializado** (`db/inbound_jobs.claim_next_inbound_job`): por conversación
  candidata se toma `pg_try_advisory_xact_lock(tenant:conversation)`. Si ya hay un
  job `running` con lease vigente, se salta. El lock es de transacción, así que sirve
  con el pooler en cualquier modo. Durante el turno, la exclusión la da el estado
  `running` más `locked_until`, que se renueva con un heartbeat.
- **Ráfagas**: si llegan varios mensajes mientras la conversación está ocupada, se
  procesa solo el más nuevo con el contenido de todos, y los anteriores pasan a
  `superseded`. Resultado: una sola respuesta a la ráfaga. El historial del turno se
  acota a su mensaje (`get_recent_messages(up_to_message_id=…)`).
- **Fallos**: si algo falla antes o durante el grafo, se reintenta con backoff (30 s,
  120 s y 300 s, máximo 3 intentos). Al agotarlos, el job queda `failed` y se emite
  `logger.error`. La entrega, la resolución y el escalado son best-effort y no se
  reintentan, porque la respuesta pudo haber salido ya. Un job reintentado comprueba
  primero si su inbound ya tiene respuesta del agente (`metadata.inbound_message_id`),
  así que nunca responde dos veces. En el shutdown, el job en curso vuelve a
  `pending`.

## Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| **Cloud Tasks** | Resuelve bien el despertar con `min=0` (es push HTTP), pero mete infra y credenciales GCP nuevas, acopla el core a un proveedor y no resuelve la serialización por conversación: igual haría falta el lock en Postgres. Con `--no-cpu-throttling` y `max=1`, el worker en proceso más la recuperación por lease cubre el caso. Si pasamos a varias instancias o a `min=0` con picos largos sin tráfico, se puede reevaluar para despertar a la instancia (el consumo seguiría en Postgres). |
| **`BackgroundTasks` / `asyncio.create_task` sin cola** | Se pierde el trabajo si la instancia se reinicia o escala a 0 a mitad del turno. |
| **Advisory lock de sesión durante todo el turno** | Obliga a retener una conexión dedicada unos 30 s por turno y depende del modo del pooler. Con Supavisor en modo transacción, el lock de sesión no es seguro. |
| **Redis / broker externo** | Otra pieza que operar para un volumen que Postgres absorbe de sobra. |

## Consecuencias

**Positivas:**
- El webhook responde en milisegundos, así que el proveedor ya no registra timeouts
  ni reintentos por la latencia del grafo.
- Una conversación nunca tiene dos turnos en paralelo, y las ráfagas dan una sola
  respuesta.
- Los turnos sobreviven a reinicios y despliegues. La cola es inspeccionable con SQL
  (`status`, `attempts`, `last_error`, latencia de cola en el log `inbound_job_done`).
- Se corrige el `409 in_flight` permanente de la idempotencia.

**Negativas / costos asumidos:**
- El webhook ya no devuelve la decisión del agente. La trazabilidad pasa al log del
  worker, a LangSmith y a la tabla `inbound_jobs`.
- Con `min=0`, si la instancia se apaga con jobs pendientes, estos esperan a la
  siguiente petición que la despierte. Hoy el siguiente webhook la despierta. Si hace
  falta, se puede añadir un ping de Cloud Scheduler.
- `/webhooks/inbound` (script de pruebas) sigue siendo síncrono y no pasa por la
  cola.
- El flujo de approvals (aprobar o rechazar L3) todavía no se serializa con los
  turnos inbound de la misma conversación.
