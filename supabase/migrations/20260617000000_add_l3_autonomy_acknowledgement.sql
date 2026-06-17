-- Piso de seguridad L3 (PR1): hacer distinguible un opt-out CONSCIENTE de la
-- aprobación humana, del default de fábrica.
--
-- Hasta ahora `human_approval_required=FALSE` era ambiguo: significaba lo mismo
-- "el tenant aceptó conscientemente operar esta L3 sin red" que "nadie configuró
-- nada / es el default de fábrica del schema". Una L3 destructiva podía ejecutarse
-- sin aprobación humana por descuido, confiando solo en el supervisor LLM (sesgado
-- a aprobar).
--
-- Con estas columnas, el opt-out de una L3 solo es válido si fue reconocido
-- explícitamente (acknowledged_at poblado). El código
-- (execute_skill._l3_requires_human_approval) trata la AUSENCIA de reconocimiento
-- como "requiere approval", sin importar human_approval_required.
--
-- No hace falta backfill: NULL = no reconocido = fail-safe. Todas las L3 existentes
-- (incluido el seed de dogfood) pasan a exigir aprobación automáticamente.

ALTER TABLE tenant_tool_permissions
    ADD COLUMN IF NOT EXISTS l3_autonomy_acknowledged_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS l3_autonomy_acknowledged_by UUID REFERENCES users(id);
