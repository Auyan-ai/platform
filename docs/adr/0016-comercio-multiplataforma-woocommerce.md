# ADR 0016 — Comercio multiplataforma: contrato de comercio común y WooCommerce como segundo proveedor

**Estado:** Propuesta (pasa a Aceptada cuando se mergeen el contrato y el adapter de WooCommerce)
**Fecha:** 2026-10-25 (sesión 88, issue [#422](https://github.com/Auyan-ai/platform/issues/422))
**Relación:** extiende las skills por niveles de [ADR 0005](0005-skills-tiered-l1-l2-l3.md), el
gate de identidad de [ADR 0013](0013-verificacion-identidad-por-niveles.md), las devoluciones
de [ADR 0014](0014-devoluciones-y-cambios-politica-del-tenant.md) y la ingesta de
[ADR 0015](0015-url-a-agente.md).

## Contexto

Shopify es hoy el único proveedor de comercio, y el código lo da por hecho:

- Las 11 skills de `skills/shopify/` construyen `ShopifyAdapter()` ellas mismas cuando el turno
  no inyecta un adapter (`ctx.commerce_mock or ShopifyAdapter()`). Lo mismo hacen
  `execute_skill._refs_point_to_same_order` y `identity_guest`.
- `load_tenant_context` serializa el `IntegrationContext` de comercio sin el proveedor, así que
  aguas abajo nadie sabe de qué plataforma es.
- Los tipos que deciden una L3 (`OrderSnapshot`, `RefundRoute`, `RefundableBalance`,
  `MarkedRefund`, `SnapshotTransaction`) ya son neutros, pero viven en `integrations/shopify.py`.
- Los pedidos que leen las skills y el gate de identidad (`order_claims`) tienen la forma REST de
  Shopify (`name`, `email`, `phone`, `financial_status`, `fulfillments`, `line_items`,
  `shipping_address`, `*_set.presentment_money`). El simulador y `DemoCatalogAdapter` ya
  devuelven esa misma forma.
- Las descripciones que ve el LLM dicen "pedido de Shopify".

Chatbase no tiene integración con WooCommerce (s87). WooCommerce es la plataforma más usada por
las pymes españolas que no están en Shopify. Kenny decidió (s88) integrarla igual de a fondo que
Shopify, con un stack modular.

Comprobado en s88 contra un WooCommerce real (WordPress Playground en local, WooCommerce de
wordpress.org, REST `wc/v3` con consumer key y secret):

- `POST /wc/v3/orders/{id}/refunds` con `api_refund: true` reembolsa por la pasarela y devuelve
  `refunded_payment: true`. Si la pasarela rechaza, WooCommerce **borra el reembolso** y responde
  500 `woocommerce_rest_cannot_create_order_refund` con el mensaje de la pasarela.
- Con una pasarela sin reembolsos automáticos (transferencia, contra reembolso) la misma llamada
  responde 500 "does not support automatic refunds". Con `api_refund: false` solo se apunta el
  reembolso y devuelve la tienda.
- `GET /wc/v3/payment_gateways` dice por pasarela si admite reembolsos
  (`method_supports` contiene `refunds`).
- WooCommerce **no admite clave de idempotencia**. El `reason` del reembolso se guarda tal cual,
  así que la marca `[auyan:<clave>]` sirve para reconciliar.
- No hay tags de pedido, ni API de devoluciones, ni seguimiento de envío en el núcleo (el
  seguimiento lo añaden plugins como Shipment Tracking en `meta_data`).
- `GET /wp-json/` da `name`, `description` y los namespaces (`wc/v3`, `wc/store/v1`). La Store
  API pública da precios en unidades menores (`"4500"` con `currency_minor_unit: 2`) y las
  variantes con su id.

## Decisión

1. **Un contrato de comercio, no uno por plataforma.** `integrations/commerce.py` define el
   protocolo `CommerceAdapter` (la superficie que usan las skills hoy), los tipos neutros que
   salen de `shopify.py` y `CommerceCapability`. La **forma canónica del pedido es la forma REST
   de Shopify** que ya consumen las skills, el gate de identidad, el simulador y la demo. Cada
   adapter la produce en su frontera. No se inventa un modelo nuevo: la forma ya existe, está
   cubierta por tests y cambiarla toca el gate de identidad.
2. **El adapter lo elige el proveedor de la integración.** El `IntegrationContext` de comercio
   lleva `provider` y el turno resuelve el adapter con
   `IntegrationRegistry.get("commerce", provider)`. Las skills usan `ctx.commerce` (el adapter ya
   resuelto: real, mock o demo) y no importan ningún adapter concreto.
3. **Capacidades en vez de ifs por plataforma.** Cada adapter declara sus `capabilities`. Cada
   skill declara la que necesita. Una skill cuya capacidad no tiene el proveedor del tenant no se
   ofrece al LLM, y si aun así llega una llamada, `execute_skill` la rechaza con
   `commerce_capability_missing` y razón explícita. Shopify las tiene todas. WooCommerce no
   tiene `returns`, `exchanges` ni `order_tags`: el agente escala esos casos al equipo, igual
   que sin política de devoluciones (ADR 0014).
4. **WooCommerce reembolsa con las mismas garantías que Shopify:**
   - `RefundRoute` sale de la pasarela del pedido. `automatic` si su `method_supports` incluye
     `refunds`, `manual` si no.
   - `automatic` llama con `api_refund: true`; `manual`, con `api_refund: false` y el
     `ActionOutcome.REFUND_MANUAL` de siempre.
   - Un 4xx o el 500 `woocommerce_rest_cannot_create_order_refund` es `MutationNotApplied`,
     porque WooCommerce no deja el reembolso. Cualquier otro fallo tras enviar deja el resultado
     sin saber y lo resuelve `reconcile`.
   - `find_refund` busca la marca `[auyan:<clave>]` en `reason`. La reclamación
     `pending → executing` de la aprobación (#376) ya impide dos ejecuciones a la vez, así que
     la falta de clave de idempotencia nativa no abre un doble reembolso.
5. **Los slugs se quedan como `shopify.*` por ahora.** Están en `tenant_tool_permissions`, en los
   AOPs canónicos y en las evals. Las descripciones pasan a ser neutras ("pedido de la tienda").
   Renombrarlos a `commerce.*` es una migración aparte, con su propio issue.
6. **Credenciales de WooCommerce:** `{"store_url", "consumer_key", "consumer_secret"}` cifradas
   en `tenant_integrations` como cualquier otra. El adapter exige HTTPS y autentica con Basic
   auth. Permisos `read_write` (las L2 y L3 escriben). Se validan al registrar la integración
   leyendo `GET /wc/v3/system_status`.
7. **Ingesta y demo (#422):** `Platform.WOOCOMMERCE` y `Platform.WORDPRESS` se detectan por
   `/wp-json/` (con `?rest_route=/` de respaldo), la fuente `wordpress_api` trae páginas y
   entradas, y `demo_catalog` elige el adapter de catálogo por la plataforma de la demo.

## Consecuencias

- Un tercer proveedor (PrestaShop, Magento, Tiendanube) es un adapter que produce la forma
  canónica y declara sus capacidades. No toca skills ni grafo.
- Las skills y el gate de identidad no cambian de lógica. El riesgo del cambio está en el
  mapeo de cada adapter a la forma canónica, y se prueba contra respuestas grabadas de un
  WooCommerce real.
- Sin tags ni devoluciones nativas, WooCommerce escala más casos que Shopify. Es lo correcto
  hasta que haya clientes que pidan los plugins de devoluciones (#383).
- Un WooCommerce detrás de un firewall que bloquee Basic auth, o con un plugin de numeración
  de pedidos (Sequential Order Numbers), necesita su caso en el adapter: el número visible se
  busca con `search` y se compara con `number`, no con `id`.

## Alternativas descartadas

- **Un modelo de pedido nuevo y neutro (dataclasses) para todas las skills.** Más limpio sobre el
  papel, pero reescribe 11 skills, el gate de identidad, el simulador y sus fixtures a la vez,
  sin cambiar lo que hace el agente. La forma REST de Shopify ya funciona como contrato.
- **Skills `woocommerce.*` duplicadas.** Duplica la lógica de las L3 (guardas, veredictos,
  textos fijos) y cada arreglo habría que hacerlo dos veces.
- **Pedir el `id` interno a la tienda en vez del número visible.** El cliente ve `number`, y con
  un plugin de numeración secuencial no coincide con `id`.
