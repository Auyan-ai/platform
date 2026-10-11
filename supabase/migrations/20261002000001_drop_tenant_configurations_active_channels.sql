-- Elimina tenant_configurations.active_channels: la tarjeta de integraciones
-- se deriva de tenant_integrations (#301). El tipo channel_type se conserva
-- (lo usan otras tablas).
ALTER TABLE tenant_configurations DROP COLUMN IF EXISTS active_channels;
