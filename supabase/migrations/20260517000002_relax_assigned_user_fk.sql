-- Permite que super_admin (con tenant_id propio) tome escalaciones/conversaciones
-- de cualquier tenant. La FK composite (assigned_user_id, tenant_id) → users(id, tenant_id)
-- restringía el agente al mismo tenant que la escalación/conversación.
--
-- Reemplaza por una FK simple a users(id): garantiza que el usuario existe,
-- pero no fuerza coincidencia de tenant. La autorización por rol/tenant la hace
-- la capa de servicio.

-- ─── escalations ──────────────────────────────────────────────────────────────

alter table escalations
  drop constraint escalations_assigned_user_id_tenant_id_fkey;

alter table escalations
  add constraint escalations_assigned_user_id_fkey
  foreign key (assigned_user_id) references users(id);

-- ─── conversations ────────────────────────────────────────────────────────────

alter table conversations
  drop constraint conversations_assigned_user_id_tenant_id_fkey;

alter table conversations
  add constraint conversations_assigned_user_id_fkey
  foreign key (assigned_user_id) references users(id);
