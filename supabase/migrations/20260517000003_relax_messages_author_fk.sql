-- Mismo problema que la migración previa pero en `messages.author_user_id`:
-- la FK composite (author_user_id, tenant_id) → users(id, tenant_id) bloquea a
-- super_admin (con tenant_id propio) cuando responde una conversación de otro tenant.
--
-- Aplicada manualmente en staging vía psql para destrabar el flujo de "responder".

alter table messages
  drop constraint messages_author_user_id_tenant_id_fkey;

alter table messages
  add constraint messages_author_user_id_fkey
  foreign key (author_user_id) references users(id);
