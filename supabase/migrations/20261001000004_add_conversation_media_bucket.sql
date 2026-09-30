-- Sprint 2 · PR-7: bucket PRIVADO para los adjuntos de los compradores (WhatsApp).
--
-- Meta borra la media entrante tras un tiempo: Auyan la descarga al procesar el turno y
-- la guarda aquí. Ruta: {tenant_id}/{conversation_id}/{message_id}/{idx}.{ext}.
-- Sin políticas públicas ni de `authenticated`: solo la service role (la API) lee y
-- escribe. La vista previa en el dashboard (URL firmada) queda fuera de este sprint.
-- Límite: 16 MB por archivo (el de WhatsApp).

insert into storage.buckets (id, name, public, file_size_limit)
values ('conversation-media', 'conversation-media', false, 16777216)
on conflict (id) do update
  set public = false,
      file_size_limit = excluded.file_size_limit;
