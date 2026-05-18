-- Sprint 9.5: columna nudged_at en conversations para rastrear recordatorios enviados.
-- El job de cleanup usa esta columna para saber si ya envió el nudge a una conversación inactiva.
-- Una vez seteada, no se vuelve a mandar otro nudge aunque la conversación siga abierta.

ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS nudged_at timestamptz;

COMMENT ON COLUMN conversations.nudged_at
    IS 'Timestamp del recordatorio enviado antes del cierre automático. NULL = no enviado todavía.';
