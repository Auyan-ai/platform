-- Auyan — #378: por qué el clasificador de AOP cayó a `default` sin decisión
-- (NoDecision.reason: refusal, max_tokens, sin tool, llamada fallida, salida inválida).
-- Nullable: NULL = el clasificador sí decidió. La tabla ya tiene tenant_id, RLS y created_at.
-- Orden: aplicar ANTES O DESPUÉS del deploy; sin la columna el código inserta sin la razón
-- y deja un logger.error `intent_classifier_fallback_reason_column_missing`.

begin;

alter table intent_classifier_runs
  add column if not exists fallback_reason text;

comment on column intent_classifier_runs.fallback_reason is
  'Razón por la que el clasificador no decidió y el turno cayó a default (NoDecision.reason).';

commit;
