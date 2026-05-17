-- Sprint 6.4: lifecycle de conversación
-- Agrega el estado `closed_abandoned` para conversaciones cerradas por inactividad.
-- ALTER TYPE ... ADD VALUE es DDL irreversible — solo se puede agregar al final del enum.

ALTER TYPE conversation_status ADD VALUE IF NOT EXISTS 'closed_abandoned';
