-- Auyan — ADR 0015 §3 / PR 1: ciclo de vida de la KB.
-- Una fuente es un documento y se puede sustituir. Añade:
--   * knowledge_base_documents.source_key / content_sha256, e índice único parcial
--     (tenant_id, source_key) entre los documentos vivos.
--   * knowledge_base_chunks.deleted_at, para que la búsqueda excluya los chunks muertos
--     dentro del escaneo HNSW.
--   * tenant_knowledge_submissions.source_key y el valor 'superseded' del enum.
--
-- Duplicados existentes (decisión determinista, antes de crear el índice): entre los documentos
-- vivos con la misma (tenant_id, clave canónica de `source`) se conserva el MÁS NUEVO
-- (created_at desc, id desc) y los más viejos se borran en blando, con
-- metadata.superseded_by_migration. Sus chunks se marcan borrados en el mismo paso.
--
-- Submissions: el enum gana 'superseded', pero Postgres no deja usar un valor recién añadido
-- en la misma transacción. Por eso la migración NO resuelve pendientes duplicados ni crea un
-- índice único de submissions; la unicidad de pendientes por (tenant_id, source_key) la
-- impone el código (lock consultivo + supersede) al crear la submission.
--
-- content_sha256 queda NULL en los documentos antiguos (se calcula sobre el texto normalizado
-- al aprobar, no se reconstruye aquí).
--
-- Orden de despliegue: aplicar ANTES del deploy del API (el código nuevo lee estas columnas).

begin;

alter type tenant_knowledge_submission_status add value if not exists 'superseded';

-- Misma regla que apps/api/services/kb_source_key.py: host en minúsculas, sin esquema,
-- sin 'www.', sin query ni fragmento, sin '/' finales.
create or replace function kb_canonical_source_key(url text)
returns text
language sql
immutable
as $$
  select regexp_replace(
    regexp_replace(lower(split_part(s.rest, '/', 1)), '^www\.', '')
      || substr(s.rest, length(split_part(s.rest, '/', 1)) + 1),
    '/+$',
    ''
  )
  from (
    select split_part(
             split_part(regexp_replace(btrim(url), '^https?://', '', 'i'), '#', 1),
             '?', 1
           ) as rest
  ) s
$$;

alter table knowledge_base_documents
  add column if not exists source_key text,
  add column if not exists content_sha256 text;

alter table knowledge_base_chunks
  add column if not exists deleted_at timestamptz;

alter table tenant_knowledge_submissions
  add column if not exists source_key text;

-- Duplicados: se queda el documento vivo más nuevo de cada (tenant_id, clave).
with ranked as (
  select id,
         row_number() over (
           partition by tenant_id, kb_canonical_source_key(source)
           order by created_at desc, id desc
         ) as rn
    from knowledge_base_documents
   where deleted_at is null
     and source ~* '^https?://'
     and kb_canonical_source_key(source) <> ''
)
update knowledge_base_documents d
   set deleted_at = now(),
       metadata = d.metadata || jsonb_build_object(
         'superseded_by_migration', '20261025000001_kb_document_lifecycle'
       )
  from ranked r
 where d.id = r.id and r.rn > 1;

update knowledge_base_documents
   set source_key = kb_canonical_source_key(source)
 where deleted_at is null
   and source ~* '^https?://'
   and kb_canonical_source_key(source) <> '';

-- Los chunks heredan el borrado en blando de su documento (incluye los de antes de la migración).
update knowledge_base_chunks c
   set deleted_at = d.deleted_at
  from knowledge_base_documents d
 where d.id = c.document_id
   and d.tenant_id = c.tenant_id
   and d.deleted_at is not null
   and c.deleted_at is null;

update tenant_knowledge_submissions
   set source_key = kb_canonical_source_key(source_url)
 where source_url ~* '^https?://'
   and kb_canonical_source_key(source_url) <> '';

create unique index if not exists uq_kb_docs_tenant_source_key
  on knowledge_base_documents(tenant_id, source_key)
  where deleted_at is null and source_key is not null;

create index if not exists idx_tenant_knowledge_submissions_pending_key
  on tenant_knowledge_submissions(tenant_id, source_key)
  where status = 'pending_review' and deleted_at is null and source_key is not null;

comment on column knowledge_base_documents.source_key is
  'Clave canónica de la fuente (URL sin esquema, www, query, fragmento ni barra final). NULL para texto y archivos.';
comment on column knowledge_base_documents.content_sha256 is
  'SHA-256 del contenido normalizado al aprobar; sirve para no reindexar lo que no cambió.';
comment on column knowledge_base_chunks.deleted_at is
  'Borrado en blando heredado del documento; la búsqueda excluye los chunks con valor.';

commit;
