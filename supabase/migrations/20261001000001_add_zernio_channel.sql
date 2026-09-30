-- Sprint 2 · PR-2: WhatsApp vía Zernio (ADR 0010).
--
-- 1. Routing del webhook de Zernio por `config->>'account_id'`: una cuenta de WhatsApp
--    activa mapea a exactamente un tenant (espejo de add_integration_routing_unique).
-- 2. Un teléfono por cliente y tenant: la identidad de WhatsApp se resuelve por BSUID
--    (`end_customers.external_id`, ya único) → teléfono → email.
-- 3. Sesiones sobre el chat: un chat de WhatsApp no termina. Solo puede haber UNA
--    conversación viva por (tenant, canal, external_id); las cerradas o resueltas no
--    bloquean que se abra otra sobre el mismo chat. En helpdesks no cambia nada: un
--    ticket sigue teniendo una sola conversación.
--
-- ⚠️ PRE-REQUISITOS (si fallan, el CREATE UNIQUE INDEX aborta la migración):
--   -- cuentas de Zernio duplicadas (no debería haber ninguna antes de esta migración)
--   SELECT config->>'account_id', count(*) FROM tenant_integrations
--    WHERE provider = 'zernio' AND kind = 'channel' AND deleted_at IS NULL AND is_active
--    GROUP BY 1 HAVING count(*) > 1;
--   -- teléfonos duplicados por tenant
--   SELECT tenant_id, phone, count(*) FROM end_customers
--    WHERE phone IS NOT NULL AND deleted_at IS NULL
--    GROUP BY 1, 2 HAVING count(*) > 1;
--   Fusionar o soft-deletear los duplicados (deleted_at = now()) antes de aplicar.

CREATE UNIQUE INDEX tenant_integrations_unique_zernio_account
    ON tenant_integrations ((config->>'account_id'))
    WHERE provider = 'zernio'
      AND kind = 'channel'
      AND deleted_at IS NULL
      AND is_active = TRUE
      AND config->>'account_id' IS NOT NULL;

CREATE UNIQUE INDEX uq_end_customers_phone
    ON end_customers (tenant_id, phone)
    WHERE phone IS NOT NULL AND deleted_at IS NULL;

DROP INDEX IF EXISTS uq_conversations_external;
CREATE UNIQUE INDEX uq_conversations_external
    ON conversations (tenant_id, channel, external_id)
    WHERE external_id IS NOT NULL
      AND deleted_at IS NULL
      AND status NOT IN ('closed', 'closed_abandoned', 'resolved');

-- Lookup de la sesión más reciente de un chat (find_conversation_by_external).
CREATE INDEX IF NOT EXISTS idx_conversations_external_recent
    ON conversations (tenant_id, channel, external_id, created_at DESC)
    WHERE external_id IS NOT NULL AND deleted_at IS NULL;
