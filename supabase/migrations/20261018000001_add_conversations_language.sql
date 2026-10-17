-- Idioma de la conversación (ISO 639-1), decidido en código con lingua
-- (apps/api/services/language.py). NULL = aún no detectado: se usa el defecto del tenant.
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS language TEXT;
