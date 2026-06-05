-- Chip #3: resolución autónoma del agente.
-- `resolved_at` marca cuándo el agente resolvió la conversación (status='resolved').
-- Invariante: resolved_at IS NOT NULL  <=>  status='resolved'. Se limpia al reabrir.
-- Habilita el conteo de resoluciones por periodo (billing por resolución, ver PRD)
-- y medir la antigüedad de la resolución para la ventana de reapertura.

ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS resolved_at timestamptz;

-- Índice parcial para el conteo de resoluciones por tenant/periodo (billing).
CREATE INDEX IF NOT EXISTS idx_conversations_resolved_at
    ON conversations (tenant_id, resolved_at)
    WHERE resolved_at IS NOT NULL AND deleted_at IS NULL;
