# ADR 0014 — Devoluciones y cambios: política del tenant, decidida en código y sin valores por defecto

**Estado:** Propuesta (pasa a Aceptada cuando se mergee la implementación)
**Fecha:** 2026-10-18 (sesión 86, issue [#320](https://github.com/Auyan-ai/platform/issues/320))
**Relación:** usa el gate de identidad de [ADR 0013](0013-verificacion-identidad-por-niveles.md) y
las L3 de [ADR 0005](0005-skills-tiered-l1-l2-l3.md).

## Contexto

Hoy solo existe `shopify.start_return` (L3), que llama a `returnCreate`:

- No comprueba la ventana de devolución. "Solo si está entregado" vive en la descripción para
  el LLM, y el AOP `returns` le pide al LLM que calcule el plazo con fechas.
- El motivo es texto libre, y un mapeo por palabras lo convierte en un motivo de Shopify.
- No hay cambios (exchanges).
- Nadie calcula qué se devuelve, quién paga el envío ni el neto.
- El texto al cliente lo redacta el LLM, que puede dar a entender que el dinero ya vuelve.

`tenant_facts.return_window_days` existe, pero solo llega al prompt como texto.

**Decisión de Kenny (s86):** Auyan monta la infraestructura y cada tenant decide su política.
No hay valores por defecto: ni 30 días, ni quién paga el envío, ni qué motivos valen. Sin
política configurada, el agente no abre devoluciones ni cambios: el código rechaza con un
resultado tipado y escala con razón explícita.

Comprobado en la documentación de la Admin API 2026-04 y con lecturas sobre Marea:

- `returnCreate(returnInput: ReturnInput!)` (scope `write_returns`) acepta
  `exchangeLineItems` (`variantId`, `quantity`) en el **mismo pedido**, `returnShippingFee`
  (importe en la moneda de presentación del pedido) y `requestedAt`. `notifyCustomer` está
  deprecado.
- `returnCalculate` (scope `read_returns`) calcula sin crear nada: subtotal e impuesto por
  línea devuelta (en negativo) y por línea de cambio (en positivo), y la tarifa de envío.
  En un pedido con `taxesIncluded = true` el subtotal ya lleva el impuesto.
- `Fulfillment` trae `createdAt` (envío) y `deliveredAt` (entrega, solo si el transportista
  o la tienda la marcan). En Marea, #1431 tiene `deliveredAt` y los pedidos de mayo no.
- `returnReasonDefinitions` es una librería global de motivos con `handle` estable
  (`too-small`, `damaged-or-defective`, `changed-my-mind`…).

## Decisión

**La política de devoluciones y cambios es un documento tipado y versionado por tenant, en
una tabla propia. Las skills `start_return` y `start_exchange` la aplican en código antes de
pedir aprobación y otra vez al ejecutar. El LLM elige artículo, motivo y variante de la lista
que le da el código, y redacta. Sin política, rechazo tipado y escalado.**

### 1. Modelo de la política

`services/returns_policy.py`, Pydantic estricto (`extra="forbid"`, inmutable) con
`schema_version: Literal[1]`:

| Campo | Qué decide |
|---|---|
| `window.days` (1–365) y `window.starts_at` (`delivery`, `shipment` u `order`) | Plazo y evento desde el que cuenta |
| `reasons[]`: `code`, `label`, `fault` (`store` o `customer`), `required_evidence` (`photo`), `shopify_reason` (handle, opcional) | Lista cerrada de motivos, de quién es la culpa y qué pruebas exige cada uno |
| `shipping.method` (`customer_ships` con `return_address`, o `store_label`) | Cómo vuelve el paquete |
| `shipping.payer.store_fault` y `shipping.payer.customer_fault` (`store` o `customer`) | Quién paga el envío de vuelta según la culpa |
| `shipping.customer_fee` (importe + moneda ISO) | Lo que se descuenta del reembolso cuando paga el cliente y la tienda pone la etiqueta |
| `refund_days` (1–60) | Plazo de reembolso desde que la tienda recibe el artículo |
| `excluded_product_tags[]` | Productos que no admiten devolución (por etiqueta de Shopify) |
| `exchanges.enabled` y `exchanges.kinds` (`variant`, `product`) | Si hay cambios y de qué tipo: otra variante del mismo producto, o cualquier producto |
| `returns_require_approval` | Si una devolución sin cambio necesita aprobación humana |

Los validadores cruzados hacen ilegales los estados sin sentido: `customer_ships` exige
dirección; `customer_fee` solo con `store_label` y cuando algún lado paga el cliente, y es
obligatoria en ese caso; los códigos de motivo son únicos; con `exchanges.enabled`, `kinds`
no está vacío.

### 2. Dónde vive: tabla `tenant_returns_policies`, no `tenant_facts`

Una fila por versión, solo inserciones: `tenant_id`, `version`, `schema_version`, `policy
jsonb`, `edited_by`, timestamps y `deleted_at`. La política vigente es la última versión no
borrada.

| Opción | Por qué no / por qué sí |
|---|---|
| `tenant_facts.data` | El `PUT /tenants/me/facts` reemplaza todo el JSON y el formulario tiene un campo de JSON libre: una edición de los datos de contacto podría borrar o romper la política sin pasar por el validador. Solo guarda la última versión, sin historia. |
| `tenant_configurations.extra` (como `identity_policy`) | Lo edita solo el `super_admin`, y esta política la decide el cliente. |
| **Tabla propia, versiones solo con insert** | La política autoriza acciones sobre dinero: cada cambio queda con autor, fecha y contenido completo, y la aprobación L3 cita la versión aplicada. Concurrencia optimista con `expected_version` (409 si otro guardó antes). RLS: el tenant lee e inserta lo suyo; actualizar (soft delete) solo `super_admin`. |

`tenant_facts.return_window_days` deja de llegar al prompt y sale del formulario de datos y
del onboarding: una sola fuente de verdad.

### 3. Edición

`GET` y `PUT /tenants/me/returns-policy` (`tenant_admin` y `super_admin` con `X-Tenant-Id`).
El `PUT` valida con el mismo modelo, inserta la versión nueva y loguea autor y versión. El
dashboard muestra el formulario en `/clients/<id>/returns` y en la ficha del tenant del
`super_admin`, con la misma validación en el navegador y el historial de versiones.

### 4. Decisión de una devolución o un cambio (código, sin LLM)

`evaluate_return(policy, order, request, evidence, now)` es una función pura. Recibe el
pedido releído de Shopify (líneas devolvibles con su envío y su entrega, etiquetas del
producto, `taxesIncluded`, moneda) y devuelve un plan o un rechazo tipado.

| Rechazo | Quién lo resuelve | Qué pasa |
|---|---|---|
| `policy_missing` | El equipo | Texto fijo y escalado |
| `outside_window` (con la fecha límite) | El equipo | Texto fijo y escalado |
| `delivery_date_unknown` (cuenta desde la entrega y Shopify no la tiene) | El equipo | Texto fijo y escalado |
| `product_excluded` o `product_unknown` | El equipo | Texto fijo y escalado |
| `exchanges_disabled` | El equipo | Texto fijo y escalado |
| `evidence_unreadable` (exige foto y el canal no trae adjuntos a Auyan) | El equipo | Texto fijo y escalado |
| `reason_not_in_policy` (con la lista de códigos) | El LLM | Error tipado: elige un motivo de la lista |
| `evidence_missing` (falta la foto en la conversación) | El LLM | Error tipado: pide la foto |
| `item_not_returnable`, `quantity_exceeds_returnable` | El LLM | Error tipado, con las líneas devolvibles |
| `exchange_kind_not_allowed`, `exchange_variant_unavailable` | El LLM | Error tipado: ofrece otra opción |

Lo que escala usa `SkillRefusal` (texto fijo al cliente, razón al equipo). Lo que el cliente
puede arreglar usa `SkillRejection`, nuevo: vuelve al LLM como error tipado. Los dos quedan en
`skill_audit_log` (`rejected_by_permissions`, `skill_refused: <code>` o `skill_rejected:
<code>`), en `agent_reasoning_events` y en la traza de LangSmith de `execute_skill`.

**Pruebas.** Una foto cuenta si algún mensaje del cliente en el historial del turno trae un
adjunto de tipo imagen. Hoy solo WhatsApp guarda adjuntos en `messages.attachments`: en los
demás canales, un motivo con foto obligatoria escala (`evidence_unreadable`) en vez de pedir
algo que el código no verá. La tarjeta de aprobación lleva la referencia a cada foto.

### 5. Liquidación

`Settlement`, en la moneda de presentación del pedido, a partir de `returnCalculate`:
artículos devueltos (subtotal más impuesto si el pedido no lo incluye), artículos de cambio,
envío de vuelta según la culpa del motivo y neto (positivo: se le devuelve al cliente;
negativo: el cliente debe la diferencia). Si la tarifa de la política está en otra moneda, no
se resta ni se manda a Shopify: la liquidación lo marca para el humano. La liquidación va en
la aprobación L3, en la salida de la skill y, tras crear la devolución, en la nota del pedido
de Shopify (se añade a la nota que hubiera).

### 6. Aprobación

`Skill.prepare_approval` pasa a `Skill.prepare` y corre en los dos caminos (con y sin
aprobación). Así el plan de la tarjeta lo escribe siempre el código, y un `plan` que mande el
LLM se sobrescribe. La aprobación es obligatoria si el piso L3 de hoy la exige
(`tenant_tool_permissions`) **o** si el plan la exige: `returns_require_approval` para
devoluciones y **siempre** para cambios, porque un cambio envía mercancía nueva. Al ejecutar,
la skill vuelve a leer Shopify (líneas aún devolvibles, variante disponible, pedido no
cancelado) y crea exactamente lo aprobado, con `requestedAt` = momento de la petición: la
ventana se juzgó entonces, no al aprobar.

### 7. Cambios: mismo pedido

`shopify.start_exchange` crea la devolución con `exchangeLineItems` en el pedido original.
Shopify ya calcula y guarda la diferencia, y el artículo nuevo sale por el flujo de envío de
la tienda. No se crea un borrador de pedido nuevo como en Chatbase: sería una segunda
fuente de verdad sobre el mismo cambio y obliga a cuadrar a mano el crédito.

### 8. Texto al cliente

Todo texto sobre el resultado sale del catálogo `services/fixed_texts.py` (es, en, ca, fr).
Al abrir la devolución se dice que **se ha abierto**, nunca que el dinero vuelve. Los pasos
siguientes salen de la política: dirección de envío o etiqueta, quién paga, la tarifa que se
descuenta y el plazo de reembolso tras recibir el artículo. Para un cambio, la diferencia a
pagar o a devolver sale de la liquidación.

### 9. Qué ve el LLM

`load_tenant_context` carga la política vigente. Si el AOP permite `start_return` o
`start_exchange`, el bloque volátil del turno lleva un resumen generado en código: plazo,
códigos y nombres de motivo, pruebas por motivo, si hay cambios y de qué tipo. Sin política,
una línea dice que no está configurada. El AOP `returns` pierde las reglas de plazo y fechas.

### 10. Qué decide el código y qué hace el LLM

| Paso | Código | LLM |
|---|---|---|
| Plazo, evento de inicio, entrega | Sí | Nada |
| Motivo válido, culpa, envío | Sí | Elige el código de la lista |
| Pruebas presentes | Sí | Pide la foto si falta |
| Artículo devolvible, cantidad, exclusiones | Sí | Elige artículo y cantidad con el cliente |
| Cambio permitido y variante disponible | Sí | Propone la variante |
| Aprobación necesaria | Sí | Nada |
| Liquidación | Sí | Nada |
| Texto del resultado | Texto fijo | Nada |
| Resto de la conversación | Nada | Redacta |

## Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| Valores por defecto (30 días, cliente paga si cambia de opinión) | Decisión de Kenny: cada tenant decide; un defecto inventado obliga a la tienda a algo que no ha aceptado. |
| Política en `tenant_facts` | Ver punto 2. |
| Reglas en el prompt o en el AOP | El LLM calcularía fechas y decidiría elegibilidad. |
| Cambio con borrador de pedido (Chatbase) | Ver punto 7. |
| `returnRequest` + `returnApproveRequest` de Shopify | La aprobación ya vive en Auyan; dos aprobaciones confunden al equipo. |
| Calcular la liquidación con los precios de línea del pedido | Repite el reparto de descuentos e impuestos que Shopify ya hace en `returnCalculate`. |
| Portal de devoluciones (Loop, AfterShip) en esta versión | Exige un tercer tipo de salida (enlace sin escalar). Queda como issue. |

## Consecuencias

**Positivas:**

- Ninguna devolución ni cambio sin una política que el tenant aceptó, y cada uno cita la
  versión aplicada.
- Plazo, culpa, pruebas, envío y liquidación son deterministas y tienen tests.
- El cliente nunca lee que su dinero ya vuelve cuando solo se abrió la devolución.

**Negativas / costes asumidos:**

- Hasta que cada tenant configure su política, toda devolución escala. Marea incluida.
- Con `starts_at = delivery`, los pedidos sin `deliveredAt` escalan. El formulario lo explica.
- Las pruebas por foto solo funcionan por WhatsApp hasta que los intakes de helpdesk guarden
  adjuntos.
- Una tabla nueva y una skill nueva, que se aplican y siembran a mano.

## Plan de implementación

1. **PR-1 `feat:` política.** Modelo, migración, endpoints, formulario del cliente y del
   `super_admin`, retirada de `return_window_days`, este ADR. Comprobación: tests del modelo y
   de los endpoints, formulario en el navegador.
2. **PR-2 `feat:` skills.** `prepare` en los dos caminos, `SkillRejection`, adapter
   (`returnableFulfillments`, `returnCalculate`, `returnCreate` con cambio y tarifa, nota),
   `evaluate_return`, liquidación, `start_return` endurecida, `start_exchange`, textos fijos,
   bloque de política, AOP y permisos. Comprobación: tests por rama y lecturas reales de Marea.
