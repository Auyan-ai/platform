-- Auyan — #422 / ADR 0016 §7: la ingesta reconoce WooCommerce y WordPress.
--
-- Amplía el check de `site_ingestions.platform`. Orden de despliegue: aplicar ANTES del deploy
-- del API; con el API viejo y esta migración puesta no pasa nada (solo escribe 'shopify' y
-- 'other'). Con el API nuevo y sin la migración, la ingesta de una tienda WooCommerce falla al
-- pasar a `extracting`.

begin;

alter table site_ingestions drop constraint site_ingestions_platform_check;
alter table site_ingestions
  add constraint site_ingestions_platform_check
  check (platform in ('shopify', 'woocommerce', 'wordpress', 'other'));

commit;
