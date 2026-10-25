-- Auyan — ADR 0015 §5 / PR 7: tenants de demo.
-- Una demo es un tenant con origin = 'demo', sin admin y con caducidad. Añade a `tenants`:
--   * origin: 'client' (por defecto, todos los tenants existentes) o 'demo'.
--   * demo_expires_at: cuándo caduca la demo; el job de limpieza la borra en blando.
--   * demo_source_url: la URL de la tienda desde la que se creó la demo.
-- Restricción: demo_expires_at está informada si y solo si origin = 'demo'.
-- Los tenants existentes quedan como 'client' sin caducidad, así que el check se cumple.

begin;

alter table tenants
  add column origin text not null default 'client'
    check (origin in ('client', 'demo')),
  add column demo_expires_at timestamptz,
  add column demo_source_url text;

alter table tenants
  add constraint tenants_demo_expiry_matches_origin
    check ((origin = 'demo') = (demo_expires_at is not null));

-- El job de limpieza busca demos caducadas; el índice parcial lo deja barato.
create index idx_tenants_demo_expires_at
  on tenants (demo_expires_at)
  where origin = 'demo' and deleted_at is null;

commit;
