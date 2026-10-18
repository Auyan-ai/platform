-- #376: aprobar una L3 la reclama antes de ejecutarla.
--   pending   → executing  (CAS al aprobar; solo un operador lo gana)
--   pending   → rejected   (CAS al rechazar)
--   executing → approved   (consta aplicada en el proveedor)
--   executing → failed     (rechazada por una regla en código o no se puede saber si se aplicó;
--                           el caso queda escalado al equipo con la razón)
--   executing → pending    (consta que no se aplicó: se puede volver a aprobar o rechazar)
-- `reviewed_at` es el instante del clic: en una `executing`, desde cuándo ejecuta. Una
-- `executing` con `reviewed_at` antiguo es de un proceso muerto y la reconcilia el job de
-- limpieza (`services/approval_execution.recover_stale_executions`).

-- El CHECK original es anónimo (en la columna): se borra por lo que comprueba, no por nombre.
DO $$
DECLARE c record;
BEGIN
  FOR c IN
    SELECT conname FROM pg_constraint
     WHERE conrelid = 'pending_approvals'::regclass AND contype = 'c'
       AND pg_get_constraintdef(oid) LIKE '%status%'
  LOOP
    EXECUTE format('ALTER TABLE pending_approvals DROP CONSTRAINT %I', c.conname);
  END LOOP;
END $$;

ALTER TABLE pending_approvals ADD CONSTRAINT pending_approvals_status_check
    CHECK (status IN ('pending', 'executing', 'approved', 'rejected', 'failed'));

CREATE INDEX IF NOT EXISTS idx_pending_approvals_executing
    ON pending_approvals (reviewed_at)
    WHERE status = 'executing' AND deleted_at IS NULL;
