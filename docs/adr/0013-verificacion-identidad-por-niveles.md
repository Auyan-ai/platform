# ADR 0013 — Verificación de identidad en dos niveles, decidida en código (+ OTP opcional)

**Estado:** Propuesta (pasa a Aceptada cuando se mergee la implementación)
**Fecha:** 2026-10-12 (sesión 84, issue [#257](https://github.com/Auyan-ai/platform/issues/257))
**Relación:** amplía el punto 6 de [ADR 0010](0010-whatsapp-zernio-handoff.md) (L3 por email o teléfono del pedido).

## Contexto

Hoy la identidad se comprueba en dos sitios con `services/identity.check_order_ownership`: el
gate L3 (`execute_skill._l3_ownership_error`) y la dirección en `shopify.get_order_status`.
Faltan cuatro cosas:

1. **Consultar pedidos solo con un email.** `get_order_by_email` y `get_customer_history`
   reciben el email como input del LLM. Basta con escribir "mis pedidos son de ana@x.com" para
   ver los pedidos de Ana y su total gastado.
2. **Consultar con un número de pedido suelto.** `get_order_status` devuelve artículos, importes
   y tracking de cualquier número, y los números de Shopify son correlativos (`#1001`,
   `#1002`…). Las L2 (`tag_order`, `add_order_note`) no miran la identidad.
3. **El email del remitente vale lo mismo venga de donde venga.** En un ticket de chat de
   Zendesk, Gorgias o Chatwoot, el email lo teclea el visitante y nadie lo comprueba. Aun así,
   el gate lo trata igual que el remitente de un correo.
4. **La identidad sale del perfil (`end_customers`), no del mensaje.** `resolve_end_customer`
   enlaza perfiles por BSUID, teléfono y email, y con la memoria cross-canal (#256) los
   enlazará más. Un enlace heurístico no puede dar permisos.

Además, quien no escribe desde el contacto de la compra (un familiar, WhatsApp con solo BSUID,
el invitado del widget de #258) acaba siempre en "pasa el caso a una persona".

Regla dura del proyecto: **código sobre LLM**. Todo lo determinista es código con tests.

Referencia: Chatbase, acciones de Shopify, sección "Signed-in and guest customers"
(chatbase.co/docs/user-guides/chatbot/actions/shopify-actions.md). El cliente con sesión
iniciada se identifica por sesión firmada, y el invitado da email y número de pedido.

## Decisión

**Hay dos niveles, `guest` y `verified`, y los calcula el código antes de `reason`. Sin
ninguno de los dos, el agente no toca pedidos. Un gate único en `execute_skill` comprueba el
nivel y el pedido de cada skill, y la proyección de campos depende del nivel.**

### 1. Niveles

| Nivel | Cómo se obtiene | Alcance |
|---|---|---|
| ninguno | Nada de lo de abajo | Productos, políticas y KB. Ningún dato de pedidos. |
| `guest` | El cliente aporta **número de pedido + email o teléfono**, y el código comprueba que coinciden con ese pedido | **Solo ese pedido** |
| `verified` | **Remitente**, **sesión firmada** u **OTP**. Los tres valen lo mismo. | Todos los pedidos cuyo email, teléfono o cliente de Shopify coincidan con la identidad verificada |

**Remitente** significa que el mensaje llega desde el email de la compra por un ticket de
origen correo o formulario web, o desde el teléfono de la compra por WhatsApp. El origen es el
`source_channel` que el intake ya guarda (ADR 0012). Un origen de chat, messaging, API o
desconocido no da remitente. En ese caso, el email que el visitante tecleó cuenta como **dato
aportado**: sirve para `guest` si va con un número de pedido, y nunca como remitente.

Qué permite cada nivel sobre su pedido:

| Acción | `guest` | `verified` |
|---|---|---|
| Ver el pedido completo: estado, artículos, importes, tracking y dirección de envío | Sí | Sí |
| Listar "mis pedidos" | No | Sí |
| L2 (`tag_order`, `add_order_note`) | Sí | Sí |
| L3 cancelar, reembolsar, devolver | Sí, con la aprobación humana de hoy | Sí, con la aprobación humana de hoy |
| Cambiar la dirección de envío | No | Sí, con la aprobación humana de hoy |
| Cambiar datos de cuenta o perfil (skills futuras) | No | Sí |

### 2. Modelo

```python
Level = Literal["guest", "verified"]
Method = Literal["sender_email", "sender_phone", "signed_session", "otp", "order_contact"]
ClaimHash = NewType("ClaimHash", str)  # HMAC-SHA256(pii_salt del tenant, "email:…" | "phone:+34…" | "shopify_customer:…")

@dataclass(frozen=True)
class Grant:
    level: Level
    method: Method
    claims: frozenset[ClaimHash]   # verified: la identidad. guest: vacío.
    order_id: int | None           # guest: el id interno del pedido. verified: None.
    valid_until: datetime | None   # None = solo este mensaje (remitente, sesión)

@dataclass(frozen=True)
class IdentityContext:
    grants: tuple[Grant, ...]

    def level_for(self, order: ShopifyOrder) -> Level | None:
        """verified si algún claim de un grant verified toca los claims del pedido;
        guest si hay un grant guest con su order_id; si no, None."""
```

Los claims de un pedido son `order.email`, `customer.email`, los teléfonos de `order_phones()`
y `customer.id`, todos pasados por el HMAC. El estado del grafo, las tablas y las trazas
guardan solo hashes. `check_order_ownership` se sustituye por `order_claims()` más
`IdentityContext.level_for`, y sus dos callers migran en el mismo PR.

### 3. Nodo `resolve_identity` (código, sin LLM)

Va entre `load_conversation` y `select_aop`. En cada turno hace cuatro cosas, en este orden:

1. **Remitente y sesión.** Lee `messages.metadata.identity_evidence` del mensaje entrante.
   Cada intake la escribe al persistir: email del remitente con su origen, teléfono E.164 de
   WhatsApp y claims de una sesión firmada ya validada. De ahí salen los grants `verified` del
   mensaje. Nunca usa el perfil `end_customers`.
2. **Grants guardados.** Carga de `identity_checks` los grants `guest` y `otp` vigentes de
   **esta** conversación.
3. **Código OTP.** Si hay un reto pendiente, busca el código en el mensaje y lo valida (punto 6).
4. **Datos aportados.** Extrae del texto de los mensajes del cliente en esta conversación, con
   parsers y sin LLM:
   - emails, con regex y `casefold`;
   - teléfonos, con `phonenumbers.PhoneNumberMatcher` y la región del tenant;
   - números de pedido, con el patrón del tenant (`tenant_facts.order_name_pattern`, por
     defecto `#?\d{4,}`), excluyendo los dígitos que ya reconoció como teléfono.

   Suma también el email del solicitante de un ticket de chat de helpdesk. Con cada par
   (pedido, contacto) que no se haya probado antes, intenta un `guest` (punto 4).

Salidas al estado:

- `identity`: los grants, solo con hashes.
- `identity_summary`: nivel, métodos y evento OTP, para trazas.
- `identity_missing`: qué falta para tocar pedidos. Vale `["order_number", "contact"]`,
  `["contact"]`, `["order_number"]` o `[]`.

`reason` recibe en el bloque volátil del turno una línea generada por código, como "Identidad:
ninguna. Para consultar un pedido falta el número de pedido y el email o teléfono de la
compra". Nunca recibe los datos firmados ni los contactos del pedido.

### 4. `guest`: comprobación y límites

`attempt_guest(order_ref, contact)` resuelve el pedido por el adapter y compara el contacto
con los claims del pedido. Si coinciden, guarda un grant `guest` para ese `order_id`, válido
24 h dentro de la conversación. El pedido, ya proyectado (punto 5), entra en `known_facts`, así
el agente no necesita una llamada más.

Si el pedido no existe o el contacto no coincide, la salida es la misma:

- El turno termina con un **texto fijo** y no corre `reason`. Ejemplo: "No he podido verificar
  esos datos. Revisa el número de pedido y el email o teléfono con el que compraste." El texto
  nunca dice si el pedido existe.
- El intento queda en `identity_checks` con su motivo interno (`order_not_found` o
  `contact_mismatch`) para forense. Ese motivo nunca llega al cliente ni al LLM.

Límites contra la enumeración, contados en `identity_checks` con índices:

- Cada par (pedido, contacto) se prueba una sola vez por conversación.
- Como máximo se prueban 3 pares por mensaje.
- **5 fallos por conversación** bloquean `guest` en esa conversación. A partir de ahí, un texto
  fijo ofrece pasar el caso a una persona. Remitente, sesión y OTP siguen funcionando.
- **50 fallos por tenant en una hora** (configurable) registran un error con alerta y pausan
  `guest` en todo el tenant durante 15 minutos, con texto fijo. Cuesta una consulta indexada
  por intento.

Si los parsers no encuentran el dato (por ejemplo, "mi pedido es el mil dos"), el LLM tiene una
skill `identity.check_order_contact(order_number, contact)`. Esa skill llama a la misma
`attempt_guest`, con los mismos límites y el mismo texto fijo. El LLM transcribe el dato y el
código compara.

### 5. Gate único y proyección de campos

Cada skill declara qué toca y qué nivel mínimo exige, como `ClassVar`:

```python
class Skill(ABC):
    identity_scope: ClassVar[Literal["public", "order", "own_orders"]] = "public"
    min_level: ClassVar[Level | None] = None
```

| Skill | `identity_scope` | `min_level` |
|---|---|---|
| `get_product_info`, `get_shop_policies` | `public` | ninguno |
| `get_order_status`, `tag_order`, `add_order_note` | `order` | `guest` |
| `cancel_order`, `refund_partial`, `start_return` | `order` | `guest` (`verified` con `l3_requires_otp`) |
| `update_shipping_address` | `order` | `verified` |
| `list_my_orders` (sustituye a `get_order_by_email` y `get_customer_history`) | `own_orders` | `verified` |

**Skills de email.** `get_customer_history` se elimina. `get_order_by_email` pasa a ser
`shopify.list_my_orders`, **sin input**. El código busca los pedidos con el email verificado
(o el teléfono, si es lo único verificado) y nunca con un dato que escriba el LLM. Los AOPs
canónicos (`complaint`, `consulta_envio`…) se actualizan y se vuelven a sembrar.

**Lista de tools.** Antes de `reason`, el código quita de la lista de tools las skills `order`
y `own_orders` si no hay ningún grant, y las `own_orders` si no hay grant `verified`. El LLM
no puede pedir lo que no ve.

**Gate.** Va después de `tenant_tool_permissions` y antes del piso de aprobación L3, y
sustituye a `_l3_ownership_error`. Resuelve el pedido del input y llama a `level_for(order)`:

| Resultado | Qué hace el código |
|---|---|
| Nivel suficiente | Ejecuta |
| Sin grant sobre **este** pedido | Error tipado `identity_required{missing: [...]}`. El LLM pide el dato que falta. |
| `guest`, la acción exige `verified`, OTP activado | El gate crea el reto y envía el código (punto 6), y el turno termina con texto fijo: "Te he enviado un código de 6 dígitos al email de la compra. Escríbelo aquí para continuar." |
| `guest`, la acción exige `verified`, OTP apagado | Error tipado `verified_required`. El LLM explica que tiene que escribir desde el email o el teléfono de la compra, o le ofrece pasar el caso a una persona. |
| Pedido que no se resuelve | Igual que sin grant (fail-closed) |

Todo bloqueo queda en `skill_audit_log` con `status = 'rejected_by_permissions'` y
`error_message = 'identity_required'` o `'verified_required'`.

**Pedido completo para los dos niveles** (decisión de Kenny, s84). `guest` y `verified` reciben
el pedido entero, dirección de envío incluida: quien tiene el email y el número de pedido tiene
también el correo de confirmación con esos datos. No hay proyección de campos por nivel: lo que
el nivel decide es **qué pedidos** se pueden leer (el gate) y **qué acciones** se pueden
pedir. Se borran `shipping_address_withheld`, `ownership_verified` y `ownership_note` de
`OrderDetail`.

Las aprobaciones L3 no vuelven a comprobar la identidad al ejecutarse desde el dashboard. El
gate decidió al crearlas, y el operador ve con qué nivel (punto 7).

### 6. OTP (opcional, apagado por defecto)

Sirve para subir de `guest` a `verified`, por ejemplo para cambiar la dirección. Siempre lo
dispara el gate (punto 5), nunca el LLM. Requiere `identity_policy.otp_enabled = true`.

- **Destino.** El email del pedido sobre el que el cliente ya es `guest`, nunca uno que dicte
  el cliente. Solo email, por Postmark, desde `no-reply@auyan.es` con el nombre de la marca
  como remitente visible, sin seguimiento de aperturas ni enlaces. El texto lleva el código, la
  caducidad y "si no lo pediste, ignora este correo".
- **Código.** 6 dígitos de `secrets.randbelow`, guardados como `HMAC-SHA256(pepper del
  servidor, challenge_id || código)`. Caduca a los 10 minutos y admite 5 intentos. Hay un solo
  reto pendiente por conversación. Si se pide otro antes de 60 s, se devuelve el mismo. Se
  envían como máximo 3 por conversación y hora y 5 por destino en 24 h.
- **Validación en `resolve_identity`.** Con un reto pendiente, cuenta como intento un token de
  6 dígitos que no sea el número del pedido en curso. El nodo lo consume con un `UPDATE …
  WHERE status = 'pending' AND attempts < max_attempts RETURNING` atómico y lo compara con
  `hmac.compare_digest`. Los turnos ya van serializados por conversación (ADR 0008).
  - Si el código es correcto, crea un grant `verified` (método `otp`, claims del email del
    pedido) válido 30 minutos en esa conversación.
  - Si es incorrecto, ha caducado o se agotaron los intentos, el turno termina con texto fijo.
  - El token se sustituye por `[código]` antes de que lo vean `reason` o LangSmith. El widget
    lo enviará en un campo propio.
- **"L3 siempre con OTP".** Con `identity_policy.l3_requires_otp = true`, las L3 exigen un
  grant `otp` o de sesión firmada vigente, aunque el remitente coincida. Está apagado por
  defecto, y el modelo de la política rechaza activarlo con `otp_enabled = false`.

### 7. Política, trazas y aprobación humana

**Política** en `tenant_configurations.extra["identity_policy"]`, parseada con un modelo
Pydantic en `load_tenant_context`. No necesita migración.

| Clave | Default |
|---|---|
| `otp_enabled` | `false` |
| `l3_requires_otp` | `false` |
| `guest_max_failures_per_conversation` | `5` |
| `guest_max_failures_per_tenant_hour` | `50` |

Un `super_admin` cambia `otp_enabled` y `l3_requires_otp` desde el dashboard, en la ficha del
tenant. El endpoint rechaza a `tenant_admin`.

**Trazas.**

- LangSmith. `resolve_identity` entra en la allowlist `_NODE_OUTPUT_KEYS` con
  `identity_summary`, y la fila de `identity_checks` sirve para correlacionar con Supabase.
  Nunca salen claims, contactos ni códigos.
- `ReasoningTracker`. Emite `identity_resolved`, `guest_check_failed`, `guest_locked`,
  `otp_sent`, `otp_failed` y `otp_verified`.

**Aprobación humana y escalado.** El gate guarda `pending_approvals.identity_verification`
con `{level, method, matched, contact_masked, verified_at}`. El detalle de la aprobación lo
muestra en una línea: "Invitado: número de pedido + email k\*\*\*@h\*\*\*.com",
"Verificado: remitente (email de la compra)" o "Verificado: código enviado a k\*\*\*@h\*\*\*.com".
La nota interna del escalado y del handoff (ADR 0010) lleva la misma línea.

### 8. Widget con sesión firmada (#258)

Igual que Chatbase. La sesión se valida en el intake del widget, antes de persistir, y en cada
mensaje. Hay dos fuentes:

- **App Proxy de Shopify.** Shopify añade el cliente con sesión iniciada a la petición y la
  firma con el secreto de la app.
- **JWT HS256** firmado por el servidor de la tienda con un secreto por tenant
  (`tenant_integrations(kind='channel', provider='widget')`), con `exp` de 1 h como máximo y
  `aud` igual al slug del tenant.

Con firma válida, el intake escribe los claims en `identity_evidence` y el turno es
`verified`. Con firma inválida o caducada, el visitante es invitado y queda un log. Los datos
firmados nunca se pasan al LLM.

En el onboarding se lee `shop.customerAccountsV2` y se guarda en `tenant_facts`. Si la tienda
no tiene cuentas de cliente, el doctor lo avisa.

Queda como opción la acción que usa Chatbase para llevar invitados a iniciar sesión: una skill
L2 que envía el email de activación de cuenta de Shopify al email del pedido sobre el que el
cliente ya es `guest`. El spike de #258 confirma si la API lo permite con cuentas de cliente
nuevas.

### 9. Tablas

**`identity_checks`** guarda cada intento y cada grant `guest` y `otp`:

```sql
create table identity_checks (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references tenants(id),
  conversation_id  uuid not null,
  kind             text not null check (kind in ('guest', 'otp')),
  outcome          text not null check (outcome in ('granted', 'order_not_found', 'contact_mismatch', 'locked', 'paused')),
  method           text not null,
  order_id         bigint,                 -- id interno de Shopify
  claim_hashes     text[] not null default '{}',
  attempt_key      text not null,          -- hash de (pedido, contacto): dedupe por conversación
  contact_masked   text,
  valid_until      timestamptz,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  deleted_at       timestamptz,
  foreign key (conversation_id, tenant_id) references conversations(id, tenant_id)
);
create unique index uq_identity_checks_attempt on identity_checks (tenant_id, conversation_id, attempt_key) where deleted_at is null;
create index idx_identity_checks_failures on identity_checks (tenant_id, created_at desc) where outcome <> 'granted' and deleted_at is null;
-- trigger set_updated_at; RLS: is_super_admin() or tenant_id = current_tenant_id()
```

**`identity_challenges`** guarda los retos OTP: `tenant_id`, `conversation_id`, `order_id`,
`destination_hash`, `destination_masked`, `postmark_message_id`, `code_hash`, `status`
(`pending`, `verified`, `expired`, `locked`, `cancelled`), `attempts`, `max_attempts`,
`expires_at`, `verified_at`, timestamps y `deleted_at`. Tiene un índice único parcial con un
solo `pending` por conversación, y la misma RLS que `identity_checks`.

**`pending_approvals.identity_verification jsonb`**, nullable.

Ninguna tabla guarda emails ni teléfonos en claro. `services/cleanup` aplica soft delete a las
filas de más de 90 días.

### 10. Qué decide el código y qué hace el LLM

| Paso | Código | LLM |
|---|---|---|
| Extraer email, teléfono y número de pedido | Regex, `phonenumbers` y patrón del tenant, antes de `reason` | Solo si los parsers fallan: transcribe el dato a `identity.check_order_contact` |
| Validar la sesión firmada y el remitente | Sí, en el intake | Nada |
| Comparar el contacto con el pedido | Sí, con hashes | Nada |
| Decidir el nivel | Sí | Nada |
| Qué tools ve el LLM | Sí, según el nivel | Nada |
| Qué pedidos se pueden leer | Gate, según el nivel | Nada |
| Permitir o rechazar una skill | Gate, con error tipado | Nada |
| Respuesta a datos que no coinciden, bloqueo o pausa | Texto fijo, sin `reason` | Nada |
| Contar intentos y aplicar límites | Sí | Nada |
| Disparar, enviar, validar y caducar el OTP | Sí | Nada |
| Respuesta al OTP enviado o fallido | Texto fijo | Nada |
| Qué dato falta | `identity_missing` y `identity_required{missing}` | Pide al cliente el dato que falta, con la voz de la marca |
| Redactar el resto de la respuesta | Nada | Sí |

Los textos fijos viven en `services/identity_messages.py`, uno por clave, con trato de tú.
Cada tenant puede sobrescribirlos en `tenant_facts.identity_messages`. Siguen el patrón de los
mensajes fijos de ADR 0010.

### 11. Relación con #256

La identidad unificada de la memoria cross-canal sirve para **recordar**, no para
**autorizar**. Enlazar dos perfiles nunca añade grants.

### Notas de implementación (PR-3, nivel `guest`)

- `identity_checks` persiste solo `granted`, `order_not_found` y `contact_mismatch`. El bloqueo
  por conversación y la pausa del tenant se calculan contando esos fallos, así que no hay filas
  `locked` ni `paused` (contarlas como fallo habría alargado la pausa por sí sola). La pausa dura
  15 minutos desde el último fallo del tenant, mientras haya 50 o más en la última hora.
- El email que teclea el visitante de un chat se guarda en `messages.metadata.provided_contact`
  (lo escribe el intake cuando el origen no verifica el email). Es dato aportado: no crea grants
  `verified`.
- `identity.check_order_contact` es una skill `core`: la ofrece el código a todo tenant con
  commerce, sin AOP ni fila en `tenant_tool_permissions`.
- Un error del adapter de commerce al comprobar un par no se registra ni cuenta como fallo.
- Con un remitente `verified`, un par fallido no cierra el turno con texto fijo (cuenta para los
  límites). El simulador no usa `guest`.

## Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| Reglas en el prompt o en el AOP | El LLM decidiría quién está verificado. |
| Comprobación dentro de cada skill (como `get_order_status` hoy) | Repite la regla en cada skill, y una skill nueva puede olvidarla. |
| Identidad desde `end_customers` | El perfil se enlaza por heurística, y con #256 daría permisos por enlace. |
| Tres o más niveles (por ejemplo, separar remitente de OTP) | Más casos que probar sin cambiar ninguna decisión: con la aprobación humana en las L3, remitente, sesión y OTP valen lo mismo. |
| `guest` con solo número de pedido, o con solo email | Los números son correlativos y los emails circulan. Hacen falta los dos, comprobados juntos. |
| Que el LLM extraiga los datos y decida cuándo pedir el OTP | Ambas cosas son deterministas. El LLM queda como respaldo para transcribir. |
| OTP al contacto que diga el cliente | Cualquiera se verificaría a sí mismo. |
| OTP por SMS, por el helpdesk o por WhatsApp | SMS: no hay proveedor en España. Helpdesk: tres implementaciones, y el equipo CX vería el código. WhatsApp: se puede añadir si un tenant tiene pedidos solo con teléfono. |
| Enlace mágico en vez de código | Los escáneres de correo abren los enlaces solos, y no encaja en WhatsApp. |
| Preguntas de conocimiento (código postal, dígitos de la tarjeta) | Son datos que circulan en filtraciones. |

## Consecuencias

**Positivas:**

- Se cierran los huecos de consultar con un email suelto y con un número de pedido suelto.
- El familiar, WhatsApp con solo BSUID y el invitado del widget pueden reembolsar, cancelar o
  devolver con número de pedido + email, siempre con aprobación humana.
- Una sola regla en un solo sitio, y una skill nueva solo declara su alcance.
- El operador ve el nivel y el método antes de aprobar.

**Negativas / costes asumidos:**

- **Cambio visible.** Quien escribe sin datos ya no ve el estado de un pedido por su número.
  Los chats de helpdesk dejan de contar como remitente. Las fixtures de evals y del simulador
  tienen que llevar `identity_evidence` o datos aportados.
- `guest` puede pedir una L3 con datos que un tercero conozca, por ejemplo alguien de la casa
  con el email del pedido. La aprobación humana es la barrera, y `l3_requires_otp` existe para
  el tenant que quiera más.
- El remitente de un correo es falsificable en dominios sin DMARC estricto. Se mitiga con la
  aprobación humana y la línea del método.
- Los parsers fallan con números escritos en letra o con formatos raros. Para eso está la skill
  de respaldo.
- El OTP depende de que Postmark apruebe la cuenta (hoy solo entrega a `@auyan.es`).
- Dos tablas y una columna nuevas, que se aplican a mano como siempre.

## Plan de implementación

Cada PR va contra `develop` y termina en una comprobación.

1. **PR-1 `fix:` cerrar las consultas con dato suelto.**
   - `get_order_by_email` pasa a `list_my_orders` sin input, solo con remitente verificado.
   - `get_customer_history` se elimina, y los AOPs canónicos se actualizan y se vuelven a sembrar.
   - `get_order_status` devuelve solo `found=false` a quien no es dueño.
   - Un email de origen chat deja de contar como remitente.
   - Comprobación: tests de las tres skills con email ajeno, número ajeno y origen chat, más
     `/verify` sobre Marea.
   - Deja temporalmente sin acceso al no dueño hasta PR-3.
2. **PR-2 `refactor:` modelo, `resolve_identity` y gate único.** `Grant`, `IdentityContext`,
   `order_claims`, `identity_evidence` en los cuatro intakes, `identity_scope` y `min_level`
   en las skills, filtrado de tools. Borra `_l3_ownership_error` y
   `check_order_ownership`. Comprobación: tests de tabla por canal y origen, y la suite del
   gate L3 en verde.
3. **PR-3 `feat:` nivel `guest`.** Migración de `identity_checks`, parsers, `attempt_guest`,
   límites por conversación y por tenant, textos fijos, skill de respaldo y `known_facts`.
   Comprobación: tests de enumeración (respuesta idéntica para pedido inexistente y contacto
   erróneo, bloqueo al quinto fallo, pausa del tenant) y `/verify` con número + email de un
   pedido de Marea.
4. **PR-4 `feat:` nivel visible.** Migración de `pending_approvals.identity_verification`,
   línea en la aprobación, en el escalado y en el handoff, eventos del tracker y allowlist de
   LangSmith. Comprobación: `/verify` de una L3 como `guest` y captura del dashboard.
5. **PR-5 `feat:` OTP apagado por defecto.** Migración de `identity_challenges`, disparo desde
   el gate, Postmark, validación, `l3_requires_otp` e interruptor de `super_admin` en el
   dashboard. Comprobación: tests de caducidad, intentos, idempotencia y límites, y E2E en
   staging con Postmark aprobado.
6. **PR-6 `feat:` sesión firmada, con #258.** App Proxy y JWT en el intake del widget,
   `customerAccountsV2` en el onboarding y aviso del doctor. Comprobación: tests con firmas
   válidas, caducadas y alteradas.
