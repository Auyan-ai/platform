# WooCommerce real en local

Un WordPress Playground con WooCommerce de wordpress.org, para probar el adapter de comercio
(`integrations/woocommerce.py`) y las skills L3 contra una tienda de verdad. Lo usa el job
`api-woocommerce` de CI. Solo es para desarrollo: el mu-plugin baja la seguridad de la
REST y añade una pasarela de prueba.

## Qué trae

- WordPress 7.1.3, WooCommerce 11.2.1 y PHP 8.3, fijados en `blueprint.json`.
- `mu/auyan-dev.php`:
  - Fuerza HTTPS en la REST, porque WooCommerce solo acepta Basic auth sobre HTTPS.
  - Apaga el cron, el runner asíncrono de Action Scheduler y el HTTP saliente.
  - Añade la pasarela `auyan_test`, que reembolsa por API. Un motivo de reembolso con `FAIL`
    hace que la pasarela lo rechace.
  - Simula un plugin de numeración secuencial. Un pedido con la meta `_auyan_order_number`
    usa ese número visible, y la búsqueda lo encuentra.
- `mu/seed/seed.php` siembra la tienda. Crea la clave REST `read_write`, tres productos
  (uno variable), cuatro pedidos y las páginas de políticas publicadas. Si la tienda ya está
  sembrada, no hace nada.

Clave REST: `ck_auyandevlocal000000000000000000000000000`.
Secret: `cs_auyandevlocal000000000000000000000000000`.

## Arrancar

```bash
cd apps/api/scripts/woocommerce_dev
npm ci
npx wp-playground-cli server --port 9400 --php 8.3 --wp 7.1.3 \
  --blueprint ./blueprint.json --mount "$PWD/mu:/wordpress/wp-content/mu-plugins"
```

Cuando el servidor imprima `Ready!`, siembra la tienda. La primera llamada a veces devuelve
una respuesta vacía: repítela hasta ver `"seeded"`.

```bash
curl -b playground_auto_login_already_happened=1 \
  http://127.0.0.1:9400/wp-content/mu-plugins/seed/seed.php
```

Cada petición necesita la cookie `playground_auto_login_already_happened=1`. Sin ella,
Playground responde 302. La base de datos vive en memoria: al parar el servidor se pierde.

## Tests

Los tests en vivo crean sus propios pedidos, así que se pueden repetir sobre la misma tienda.
Cada petición al Playground tarda unos segundos, y la batería completa tarda unos 10 minutos.

```bash
cd apps/api
AUYAN_TEST_WOOCOMMERCE_URL=http://127.0.0.1:9400 \
  poetry run pytest tests/integrations/test_woocommerce_live.py
```

Para volver a grabar las respuestas que usan los tests unitarios
(`tests/fixtures/woocommerce/`), ejecuta desde la raíz del repo:

```bash
AUYAN_TEST_WOOCOMMERCE_URL=http://127.0.0.1:9400 \
  poetry -C apps/api run python -m apps.api.tests.woocommerce_record
```

Después revisa los valores literales de `tests/integrations/test_woocommerce_adapter.py`,
porque los ids de los pedidos cambian.

## Usar la tienda desde la API en local

El adapter exige HTTPS. Para apuntar una integración a `http://127.0.0.1:9400`, pon
`WOOCOMMERCE_ALLOW_HTTP_LOOPBACK=true` en el `.env` local. Fuera de loopback, la URL tiene que
ser HTTPS y pública siempre, tenga el flag o no.
