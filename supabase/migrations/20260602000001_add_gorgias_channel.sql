-- Gorgias ya tiene OAuth/webhook/adapter; faltaba permitirlo como canal operativo.
ALTER TYPE channel_type ADD VALUE IF NOT EXISTS 'gorgias';
