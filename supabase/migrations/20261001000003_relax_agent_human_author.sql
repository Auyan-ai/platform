-- Sprint 2 · PR-4/PR-5: mensajes 'agent_human' escritos por el equipo de la MARCA fuera de
-- Auyan (un agente de Zendesk, o la app de WhatsApp Business desde el móvil). No son
-- usuarios de Auyan, así que no tienen `author_user_id`: el autor va en
-- `metadata.external_author = {provider, id, name}`.
--
-- Antes: role = 'agent_human' ⇒ author_user_id NOT NULL.
-- Ahora: role = 'agent_human' ⇒ author_user_id NOT NULL  o  metadata ? 'external_author'.

begin;

alter table messages drop constraint messages_human_has_author;

alter table messages add constraint messages_human_has_author
  check (
    role <> 'agent_human'
    or author_user_id is not null
    or (metadata ? 'external_author' and jsonb_typeof(metadata->'external_author') = 'object')
  );

commit;
