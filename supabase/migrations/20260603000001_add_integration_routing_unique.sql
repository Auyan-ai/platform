-- H5: guard cross-tenant para el routing de webhooks de helpdesk.
--
-- Los webhooks entrantes (Chatwoot/Zendesk/Gorgias) resuelven el tenant por un
-- identificador externo guardado en config: account_id / subdomain / domain.
-- Sin unicidad, dos tenants podían tener el MISMO identificador activo y el
-- lookup (LIMIT 1) enrutaba a un tenant arbitrario → fuga cross-tenant.
--
-- Estos índices únicos parciales hacen físicamente imposible que dos
-- integraciones activas (no borradas) compartan el mismo identificador externo.
-- Cada identificador externo mapea a exactamente un tenant.
--
-- ⚠️ PRE-REQUISITO: si quedan colisiones activas, el CREATE UNIQUE INDEX falla.
-- Detectarlas antes con:
--   SELECT provider, config->>'account_id' AS k, count(*)
--     FROM tenant_integrations
--    WHERE provider = 'chatwoot' AND kind = 'helpdesk'
--      AND deleted_at IS NULL AND is_active = TRUE
--    GROUP BY 1, 2 HAVING count(*) > 1;
-- (idem subdomain/domain para zendesk/gorgias). Soft-deletear los duplicados
-- (deleted_at = NOW()) antes de aplicar esta migración.

CREATE UNIQUE INDEX tenant_integrations_unique_chatwoot_account
    ON tenant_integrations ((config->>'account_id'))
    WHERE provider = 'chatwoot'
      AND kind = 'helpdesk'
      AND deleted_at IS NULL
      AND is_active = TRUE
      AND config->>'account_id' IS NOT NULL;

CREATE UNIQUE INDEX tenant_integrations_unique_zendesk_subdomain
    ON tenant_integrations ((config->>'subdomain'))
    WHERE provider = 'zendesk'
      AND kind = 'helpdesk'
      AND deleted_at IS NULL
      AND is_active = TRUE
      AND config->>'subdomain' IS NOT NULL;

CREATE UNIQUE INDEX tenant_integrations_unique_gorgias_domain
    ON tenant_integrations ((config->>'domain'))
    WHERE provider = 'gorgias'
      AND kind = 'helpdesk'
      AND deleted_at IS NULL
      AND is_active = TRUE
      AND config->>'domain' IS NOT NULL;
