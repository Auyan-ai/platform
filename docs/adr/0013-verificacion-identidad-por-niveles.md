# ADR 0013 — Verificación de identidad por niveles, decidida en código (+ OTP)

**Estado:** Propuesta (Kenny revisa antes de programar; pasa a Aceptada cuando se mergee la implementación)
**Fecha:** 2026-10-12 (sesión 84, issue [#257](https://github.com/Auyan-ai/platform/issues/257))

## Contexto

Hoy la identidad del comprador se usa en dos sitios, los dos con la misma función
`services/identity.check_order_ownership(order, customer_email=, customer_phone=)`:

- **Gate L3** en `agents/nodes/execute_skill._l3_ownership_error`. Bloquea una L3 sobre un
  pedido si ni el email ni el teléfono del comprador coinciden con los del pedido (#259, ADR 0010).
- **Dirección en `shopify.get_order_status`**. La retiene si quien escribe no es el dueño y
  devuelve `ownership_note` para que el agente no prometa lo que el gate L3 va a bloquear.

Lo que falta, visto en el código:

1. **Las demás lecturas no comprueban nada.** `get_order_status` entrega estado, artículos,
   importes y tracking de **cualquier** número de pedido, y los números de Shopify son
   correlativos (`#1001`, `#1002`…). `get_order_by_email` y `get_customer_history` reciben el
   email **como input del LLM**: si alguien escribe "mis pedidos son de ana@x.com", el agente
   puede listar los pedidos y el total gastado de Ana. Las L2 (`tag_order`, `add_order_note`)
   tampoco miran la identidad.
2. **El email del remitente vale lo mismo venga de donde venga.** El intake de Zendesk,
   Gorgias y Chatwoot pasa el email del solicitante a `end_customers`, y el gate lo da por
   bueno. En un ticket que entró por **correo**, la respuesta vuelve a ese buzón. En un ticket
   de **chat** (Zendesk messaging, Gorgias chat, widget de Chatwoot) el email lo teclea el
   visitante y nadie lo comprueba, y la respuesta se ve en el mismo chat.
3. **La identidad sale del perfil, no del mensaje.** `build_skill_context` toma email y
   teléfono de `state["end_customer"]`. `resolve_end_customer` enlaza perfiles por BSUID,
   teléfono y email y rellena huecos. Con la memoria cross-canal (#256) un mismo perfil
   juntará identidades de varios canales, y un enlace heurístico no puede dar permisos.
4. **No hay forma de verificar a quien no escribe desde el contacto del pedido**: un familiar
   desde otro correo, WhatsApp con solo BSUID, Instagram, o un invitado en el widget (#258).
   Hoy todos esos casos acaban en "pasa el caso a una persona".

Restricciones:

- **Código sobre LLM** (ADR 0010 punto 10, ADR 0012). El LLM nunca decide si alguien está
  verificado. Solo recibe el resultado y redacta.
- El widget de chat (#258) es requisito del piloto, y en el widget el caso normal es el
  invitado sin identidad.
- Postmark ya está verificado en `auyan.es` (s83), con la cuenta pendiente de aprobación.
- Decisión s79: el OTP quedó en el backlog post-piloto. Este ADR lo diseña entero y deja la
  fecha como pregunta abierta.

Referencias del sector (investigación del issue, 2026-09-29): Decagon verifica por nivel de
riesgo y ejecuta la validación en código. Intercom Fin y Chatbase aceptan identidad firmada
(HMAC o JWT) desde la web del cliente. Gorgias fuerza confirmación en cancelar y editar
dirección.

## Decisión

**Un resolutor en código calcula, en cada turno, qué identidades están verificadas y con qué
fuerza. Un único gate en `execute_skill` compara esa identidad con el sujeto de cada skill
sensible (un pedido o un email) según la política del tenant. El OTP sube la fuerza enviando
un código al contacto que figura en Shopify, nunca al que diga el cliente.**

### 1. Modelo: verificaciones, fuerza y claims

```python
VerificationMethod = Literal["signed_session", "otp", "sender_phone", "sender_email"]
AssuranceLevel = Literal["none", "sender", "strong"]   # orden total: none < sender < strong

LEVEL: dict[VerificationMethod, AssuranceLevel] = {
    "signed_session": "strong",
    "otp": "strong",
    "sender_phone": "sender",
    "sender_email": "sender",
}

ClaimHash = NewType("ClaimHash", str)
# HMAC-SHA256(pii_salt del tenant, "email:<casefold>" | "phone:<E.164>" | "shopify_customer:<id>")

@dataclass(frozen=True)
class Verification:
    method: VerificationMethod
    claims: frozenset[ClaimHash]
    source: str                    # "zendesk:email", "whatsapp", "widget:app_proxy", "otp:<challenge_id>"
    verified_at: datetime
    valid_until: datetime | None   # None = vale mientras dure el mensaje que la aporta

@dataclass(frozen=True)
class IdentityContext:
    verifications: tuple[Verification, ...]    # vacío = sin identidad ("none")

    def level_for(self, subject: frozenset[ClaimHash], now: datetime) -> tuple[AssuranceLevel, Verification | None]:
        """La verificación vigente más fuerte cuyos claims tocan el sujeto."""
```

- **Varias verificaciones a la vez.** Un ticket de correo aporta `sender_email` del remitente.
  Si luego el remitente verifica por OTP el email de otro pedido (el caso del familiar), la
  conversación tiene dos verificaciones con claims distintos. La propiedad se decide por
  intersección: `subject_claims ∩ verification.claims ≠ ∅`.
- **Claims con hash.** El estado del grafo, el snapshot de la aprobación y la tabla del OTP
  guardan solo `ClaimHash`, nunca el email o el teléfono en claro. La comparación es una
  intersección de conjuntos. Se usa el `pii_salt` de `tenant_secrets`, que ya existe. Rotarlo
  invalida verificaciones vivas, lo que es aceptable con ventanas de minutos.
- **Claims del pedido**: `order.email`, `customer.email`, los teléfonos de `order_phones()`
  (función actual) y `customer.id` de Shopify.

`check_order_ownership(order, customer_email=, customer_phone=)` pasa a
`order_claims(order, salt, region) -> frozenset[ClaimHash]` más `IdentityContext.level_for`.
Los dos callers actuales migran en el mismo PR y la firma vieja se borra.

### 2. Resolutor de identidad: nodo `resolve_identity`

Nodo nuevo, solo código y sin LLM, entre `load_conversation` y `select_aop`:

```
load_tenant_context → load_conversation → resolve_identity → select_aop → retrieve_knowledge → reason …
```

Construye `IdentityContext` a partir de **la evidencia del mensaje entrante** y de las
verificaciones OTP vigentes de **esta** conversación. Nunca lo construye a partir del perfil
`end_customers`. El intake de cada canal escribe la evidencia en
`messages.metadata.identity_evidence` al persistir el mensaje.

| Canal y origen | Evidencia que escribe el intake | Verificación |
|---|---|---|
| WhatsApp (Zernio) con teléfono | `phone_e164` del remitente | `sender_phone` |
| WhatsApp solo BSUID, Instagram, Messenger | nada utilizable | ninguna |
| Zendesk, Gorgias o Chatwoot con origen `email` | email del solicitante | `sender_email` |
| Zendesk o Gorgias con origen formulario web | email del solicitante | `sender_email` (la respuesta vuelve a ese buzón) |
| Helpdesk con origen chat, messaging, API o desconocido | nada utilizable | ninguna |
| Widget de Auyan con sesión firmada válida (#258) | claims de la sesión validada en el intake | `signed_session` |
| Widget de Auyan como invitado | nada | ninguna |
| `/webhooks/inbound` (HMAC de Auyan, interno y de pruebas) | email del payload | `sender_email` |

El origen de un ticket de helpdesk es el `source_channel` que el intake ya guarda para ADR 0012
(Zendesk `via.channel`, Gorgias `message.channel`, Chatwoot `conversation.channel`). La lista
de orígenes que cuentan como correo vive en una tabla junto a `writing_surface._CHAT_SOURCES`.
Un origen desconocido no cuenta, al revés que en ADR 0012: un saludo de más no rompe nada,
pero una verificación de más sí.

El resolutor también procesa el OTP (punto 4): si hay un reto pendiente y el mensaje trae un
código, lo valida antes de que `reason` vea nada.

Salida al estado: `identity` (el `IdentityContext` serializado, solo con hashes) e
`identity_summary` (`{"level", "methods", "otp_event"}`). `reason` recibe una línea en el
bloque volátil del turno, por ejemplo "Identidad: verificada por el email del remitente" o
"Identidad: sin verificar". Esa línea no va en el bloque cacheado del AOP. Sirve para que el
agente no pida skills que el gate va a rechazar, pero el gate no depende de ella.

### 3. Gate único de ownership en `execute_skill`

Cada skill declara qué toca, en un `ClassVar` y no en condicionales repartidos:

```python
IdentitySubject = Literal["none", "order", "customer_email"]

class Skill(ABC):
    identity_subject: ClassVar[IdentitySubject] = "none"
    subject_field: ClassVar[str | None] = None   # "order_id" | "order_identifier" | "email"
```

| Skill | `identity_subject` | Clase de política |
|---|---|---|
| `get_product_info`, `get_shop_policies` | `none` | pública |
| `get_order_status` | `order` | `l1_pii` |
| `get_order_by_email`, `get_customer_history` | `customer_email` | `l1_pii` |
| `tag_order`, `add_order_note` | `order` | `l2` |
| `cancel_order`, `refund_partial`, `start_return`, `update_shipping_address` | `order` | `l3` |

El gate corre después de la comprobación de permisos (`tenant_tool_permissions`) y antes del
piso de aprobación L3. Sustituye a `_l3_ownership_error` y a la comprobación interna de
`get_order_status`:

1. Resuelve el sujeto: el pedido por el adapter (como hoy, visible o interno), o el email del
   input. Un pedido que no se resuelve cuenta como "sin dueño" (fail-closed, como hoy).
2. Calcula `level_for(claims del sujeto)` y lo compara con el nivel que exige la política del
   tenant para la clase de la skill.
3. Si llega al nivel, ejecuta. Si no, devuelve un error estructurado al loop ReAct:
   `identity_required` con `required_level`, `current_level` y `verification_offer`
   (`"otp_email"`, `"otp_phone"` o `null` según la política y los contactos del pedido).
   Nunca devuelve el contacto del pedido. El mensaje al LLM depende del canal, como hoy.
4. Hay una excepción de lectura parcial. Con `get_order_status` y política
   `l1_order_unverified = "status_only"`, el gate no bloquea y pasa
   `SkillContext.disclosure = "status_only"`. La skill devuelve entonces solo `found`,
   `financial_status`, `fulfillment_status` y `shipment_status`, sin artículos, importes,
   tracking ni dirección.

Todo bloqueo queda en `skill_audit_log` con `status = 'rejected_by_permissions'` y
`error_message = 'identity_required:<nivel>'`, igual que el gate L3 de hoy.

Las aprobaciones L3 no vuelven a comprobar la identidad al ejecutarse desde el dashboard. El
gate ya decidió al crearlas, y el operador ve el método (punto 7).

### 4. OTP

**Quién lo pide.** Una skill de código, `identity.request_verification`, con input
`{order_id}` o `{email}`. El LLM decide **cuándo ofrecerlo**: tras un `identity_required` con
`verification_offer`, pregunta al cliente si quiere recibir un código, y la pide si dice que
sí. El código decide todo lo demás: si la política permite OTP, a qué contacto va, los límites
y la validación. El gate no envía códigos solo, porque cualquiera que escriba un número de
pedido ajeno haría llegar correos no pedidos al dueño.

**Destino.** Siempre un contacto que figura en Shopify:

- Con `order_id`: el email del pedido (o del `customer`). En la v2, el teléfono del pedido.
- Con `email`: solo si Shopify tiene un cliente con ese email. Si no existe, la respuesta al
  LLM es la misma ("si el correo está registrado, le llegará un código") para no confirmar qué
  emails son clientes.
- Nunca un contacto que el cliente dicte para recibir el código.

**El código.**

- 6 dígitos de `secrets.randbelow`, guardados como `HMAC-SHA256(pepper del servidor,
  challenge_id || code)`. El código en claro no se guarda en ningún sitio.
- Caduca a los 10 minutos.
- Admite 5 intentos. Al quinto fallo el reto pasa a `locked` y el agente ofrece pasar el caso
  a una persona.
- Hay un solo reto pendiente por conversación. Pedir otro antes de 60 s devuelve el mismo
  (idempotente). Después de 60 s, el nuevo cancela el anterior.
- Límites de envío: 3 por conversación y hora, y 5 por destino (hash) y tenant en 24 h. El
  segundo límite evita el bombardeo de correos a una víctima.

**Validación en `resolve_identity`.** Hay intento si existe un reto `pending` y el mensaje trae
exactamente un token de 6 dígitos que no sea un número de pedido citado en la conversación. El
nodo consume el reto con un `UPDATE … WHERE status = 'pending' AND attempts < max_attempts
RETURNING` atómico y compara con `hmac.compare_digest`. Los turnos ya van serializados por
conversación (ADR 0008). Si el código es correcto, el reto pasa a `verified`, se añade una
`Verification(method="otp", claims={hash del destino}, valid_until=verified_at + 30 min)` y el
token se sustituye por `[código de verificación]` en el contenido que ven `reason` y LangSmith.
El widget enviará el código por un campo propio, sin texto libre.

**Ventana.** La verificación OTP vale 30 minutos dentro de **esa** conversación y no se
hereda en otras ni en el perfil. En WhatsApp, cuyo chat no termina nunca, la ventana es lo
que la acota.

**Canal de envío: Postmark.** Correo transaccional desde `no-reply@auyan.es` con el nombre de
la marca como remitente visible ("Marea Studio"), sin seguimiento de aperturas ni de enlaces y
con plantilla en `services/email_templates/`. El texto incluye el código, la caducidad y "si
no lo pediste, ignora este correo; nadie de {marca} te pedirá este código". El OTP por
teléfono (plantilla `AUTHENTICATION` de WhatsApp al número del pedido) queda para una v2,
cuando un tenant tenga pedidos solo con teléfono.

### 5. Política por tenant y clase

La política vive en `tenant_configurations.extra["identity_policy"]`, la edita el equipo
interno y se parsea con un modelo Pydantic en `load_tenant_context`, con defaults si falta. No
necesita migración.

| Clave | Valores | Default | Qué significa el default |
|---|---|---|---|
| `l1_pii` | `none`, `sender`, `strong` | `sender` | Leer datos de un pedido o de un cliente exige ser su dueño por el canal |
| `l1_order_unverified` | `status_only`, `none` | `status_only` | Quien no es dueño ve el estado del pedido, nada más |
| `l2` | `sender`, `strong` | `sender` | Nuevo (hoy las L2 no miran la identidad): solo el dueño anota su pedido |
| `l3` | `sender`, `strong` | `sender` | Igual que hoy, más la aprobación humana de siempre |
| `otp.enabled` | bool | `true` | Se ofrece el código cuando falta nivel |
| `otp.ttl_minutes`, `otp.max_attempts`, `otp.window_minutes` | int | 10, 5, 30 | Punto 4 |

`l3 = "strong"` es el "siempre OTP" del issue: una L3 exige OTP o sesión firmada aunque el
remitente coincida. La aprobación humana de las L3 (piso de #231) no cambia con este ADR.

### 6. Tablas y migraciones

**Nueva: `identity_challenges`.**

```sql
create table identity_challenges (
  id                  uuid primary key default gen_random_uuid(),
  tenant_id           uuid not null references tenants(id),
  conversation_id     uuid not null,
  subject_kind        text not null check (subject_kind in ('order', 'customer_email')),
  subject_ref         text not null,          -- id interno del pedido o hash del email
  destination_kind    text not null check (destination_kind in ('email', 'phone')),
  destination_hash    text not null,          -- ClaimHash del destino
  destination_masked  text not null,          -- "k***@h***.com", para el operador
  delivery_provider   text not null check (delivery_provider in ('postmark', 'whatsapp')),
  delivery_message_id text,
  code_hash           text not null,
  status              text not null default 'pending'
                      check (status in ('pending', 'verified', 'expired', 'locked', 'cancelled')),
  attempts            int  not null default 0,
  max_attempts        int  not null,
  expires_at          timestamptz not null,
  verified_at         timestamptz,
  valid_until         timestamptz,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  deleted_at          timestamptz,
  foreign key (conversation_id, tenant_id) references conversations(id, tenant_id)
);
create unique index uq_identity_challenges_pending
  on identity_challenges (tenant_id, conversation_id)
  where status = 'pending' and deleted_at is null;
create index idx_identity_challenges_destination
  on identity_challenges (tenant_id, destination_hash, created_at desc)
  where deleted_at is null;
-- trigger set_updated_at; RLS: is_super_admin() or tenant_id = current_tenant_id()
```

No guarda emails ni teléfonos en claro, solo hash y máscara. `services/cleanup` aplica soft
delete a los retos de más de 90 días.

**Cambio: `pending_approvals.identity_verification jsonb`** (nullable). Es el snapshot de la
verificación que permitió crear la aprobación (punto 7).

**Sin migración:** la política (`extra`), la evidencia del mensaje (`messages.metadata`) y el
secreto del widget (`tenant_integrations`, en #258).

### 7. Trazas, auditoría y aprobación humana

- **LangSmith.** El span de `resolve_identity` entra en la allowlist `_NODE_OUTPUT_KEYS` con
  `identity_summary` (nivel, métodos, `otp_event`: `none`, `attempt_failed`, `verified` o
  `locked`) y el `challenge_id` como metadata para correlacionar con Supabase. Nunca claims ni
  códigos. El token del código se redacta del contenido antes de llegar al LLM.
- **Razonamiento (dashboard).** `ReasoningTracker` emite `identity_resolved`,
  `verification_requested`, `verification_failed`, `verification_locked` y
  `verification_succeeded`.
- **Auditoría.** `identity.request_verification` queda en `skill_audit_log` como cualquier
  skill. Los bloqueos del gate quedan como `identity_required:<nivel>`. El ciclo de vida del
  OTP queda en la fila de `identity_challenges`.
- **Aprobación humana.** El gate escribe el snapshot en `pending_approvals.identity_verification`:
  `{"method", "level", "source", "verified_at", "matched": "email" | "phone" | "shopify_customer",
  "destination_masked"}`. El detalle de la aprobación lo muestra en una línea, por ejemplo
  "Verificado con código enviado a k\*\*\*@h\*\*\*.com hace 3 min" o "Remitente: el email de la
  compra". Si el método es `sender_email` y la acción es `update_shipping_address`, añade un
  aviso: "el remitente de un correo se puede falsificar; confirma si dudas".
- **Escalado al helpdesk.** La nota interna y el handoff (ADR 0010) incluyen la misma línea,
  para que el equipo CX sepa con quién habla.

### 8. Widget (#258) y sesión firmada

El intake del widget valida la sesión **en la frontera**, antes de persistir. Con firma válida
y sin caducar, escribe los claims (`shopify_customer:<id>` y el email) en `identity_evidence`.
Con firma inválida o caducada, trata al visitante como invitado y deja un log. No rechaza el
mensaje, para no romper el chat. La sesión se valida en cada mensaje, así que no hay estado
de sesión en Auyan.

Fuente de la firma, a confirmar en el spike del widget:

- **Tiendas Shopify: App Proxy.** Shopify añade `logged_in_customer_id` a la petición y la
  firma con el secreto de la app. El comerciante no escribe código de firma. Depende de la app
  de Shopify de Auyan (backlog transversal) o de la app por cliente del piloto.
- **Otras webs: JWT HS256** con un secreto por tenant (`tenant_integrations(kind='channel',
  provider='widget')`), `exp` de 1 h como máximo y `aud` igual al slug del tenant.

En el onboarding se lee `shop.customerAccountsV2` (`customerAccountsVersion`,
`loginRequiredAtCheckout`) y se guarda en `tenant_facts`. Si la tienda no tiene cuentas de
cliente, todos los visitantes del widget son invitados y el OTP es la única forma de pasar de
`status_only`. El doctor (`services/doctor`) lo avisa.

### 9. Relación con #256 (memoria cross-canal)

La identidad unificada de #256 sirve para **recordar**, no para **autorizar**. Que dos perfiles
estén enlazados nunca añade claims a `IdentityContext`. Los claims salen solo de la evidencia
del mensaje y de verificaciones vigentes de la conversación.

## Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| Reglas en el prompt o en el AOP ("verifica antes de dar datos") | El LLM decidiría quién está verificado. Viola código sobre LLM y no se puede testear. |
| Ownership en cada skill, como `get_order_status` hoy | Repite la regla en 9 skills y cada skill nueva puede olvidarla. Un gate con `identity_subject` declarado no se salta. |
| Identidad desde `end_customers` (como hoy) | El perfil mezcla canales y se enlaza por heurística. Con #256 daría permisos por enlace. |
| El gate envía el OTP en cuanto falla el ownership | Manda correos no pedidos al dueño cada vez que alguien cita su número de pedido. |
| OTP al email o teléfono que diga el cliente | Cualquiera se verifica a sí mismo. |
| Enlace mágico en vez de código | Los escáneres de correo (Outlook Safe Links, Gmail) abren el enlace solos, así que haría falta una página con botón. No encaja en WhatsApp. Puede añadirse después sobre la misma tabla. |
| OTP por SMS | No hay proveedor (Zernio no da SMS en España) y sería otro subencargado de PII. |
| OTP por el propio helpdesk (ticket saliente al email del pedido) | Tres implementaciones (Zendesk, Gorgias, Chatwoot), el código queda visible al equipo CX y ensucia su bandeja. |
| Preguntas de conocimiento (código postal, últimos dígitos de la tarjeta) | Son datos que circulan en filtraciones. Decagon lo pone el último de su lista. |
| Verificación persistente en el perfil, entre conversaciones | Una verificación de hace semanas no prueba quién escribe hoy. |
| Tabla propia para la política | El equipo interno es quien la edita, y `extra` con modelo Pydantic basta, como `allow_emojis`. |
| Política por skill en `tenant_tool_permissions` | Demasiado fina para lo que se acuerda en el onboarding. Las clases L1-PII, L2 y L3 bastan. |

## Consecuencias

**Positivas:**

- Se cierra el hueco de privacidad de la L1. Nadie lista los pedidos de otro por su email ni
  ve artículos, importes o tracking de un pedido ajeno.
- Una sola regla en un solo sitio. Una skill nueva declara su sujeto y queda protegida.
- El familiar, WhatsApp con solo BSUID, Instagram y el invitado del widget pueden verificarse
  sin pasar a una persona.
- El operador ve con qué fuerza se verificó cada acción antes de aprobarla.
- Los claims con hash permiten trazar y guardar snapshots sin PII.

**Negativas / costes asumidos:**

- **Cambio de comportamiento visible.** Los tickets de helpdesk de origen chat, API o
  desconocido dejan de contar como verificados, y quien no es dueño de un pedido ve menos que
  hoy. Hay que actualizar las fixtures de evals y del simulador (que hoy ponen
  `end_customer.email`) para que lleven `identity_evidence`.
- Fricción. Un invitado del widget que quiera más que el estado de su pedido tiene que
  recibir y escribir un código.
- `sender_email` sigue siendo falsificable en dominios sin DMARC estricto. Se mitiga con la
  aprobación humana de las L3, el aviso en el cambio de dirección y `l3 = "strong"` para los
  tenants que lo pidan.
- Un token de 6 dígitos puede coincidir con un número de pedido largo. Cuesta un intento, no
  verifica nada, y el widget lo evita con su campo propio.
- El OTP depende de que Postmark apruebe la cuenta. Hasta entonces solo entrega a `@auyan.es`.
- Una migración nueva (`identity_challenges`) y una columna (`pending_approvals`), que se
  aplican a mano como siempre.

## Plan de implementación

Cada PR va contra `develop`, deja el sistema funcionando y termina en una comprobación.

1. **PR-1 `refactor:` modelo de identidad y resolutor.** `IdentityContext`, `Verification`,
   `order_claims`. Nodo `resolve_identity` con `sender_email` y `sender_phone` desde
   `identity_evidence`, que escriben los cuatro intakes. Migra `_l3_ownership_error` y
   `get_order_status` y borra `customer_email` y `customer_phone` de `SkillContext`.
   Comprobación: tests de tabla del resolutor por canal y origen, la suite actual del gate L3
   en verde, y `/verify` con un ticket de origen `email` y otro de origen `chat`.
2. **PR-2 `feat:` gate único y política.** `identity_subject` en las 11 skills, gate en
   `execute_skill`, `identity_policy` con defaults y `status_only`. Comprobación: tests del gate
   por clase y nivel, evals con fixtures de no-dueño (`get_order_by_email` con email ajeno
   bloqueado, estado sin artículos), `/verify` sobre Marea.
3. **PR-3 `feat:` verificación visible.** Migración de `pending_approvals.identity_verification`,
   snapshot en el gate, línea en el detalle de la aprobación y en la nota del escalado, eventos
   del tracker y allowlist de LangSmith. Comprobación: `/verify` de una L3 y captura del
   dashboard con el método.
4. **PR-4 `feat:` OTP por email.** Migración de `identity_challenges`, skill
   `identity.request_verification`, validación en `resolve_identity`, plantilla de Postmark,
   límites y redacción del código. Comprobación: tests de caducidad, intentos, bloqueo,
   idempotencia y límites por destino, y E2E en staging con Postmark aprobado (pedido de
   Marea, código a un `@auyan.es`).
5. **PR-5 `feat:` sesión firmada (con #258).** Validación en el intake del widget (App Proxy o
   JWT), `signed_session`, lectura de `customerAccountsV2` en el onboarding y aviso del doctor.
   Comprobación: tests con firmas válidas, caducadas y alteradas, y E2E con un cliente logueado
   en la tienda de Marea.

PR-1 a PR-3 no dependen de Postmark ni del widget y cierran el hueco de la L1 por sí solos.

## Preguntas para Kenny

1. **¿Qué ve de un pedido quien no está verificado?** `status_only` (estado de pago y de envío,
   sin artículos, importes, tracking ni dirección) o nada. **Recomiendo `status_only`.** Es la
   consulta más común ("¿dónde está mi pedido?"), y el estado solo no expone datos personales
   aunque alguien pruebe números correlativos.
2. **¿Qué orígenes de ticket cuentan como "remitente verificado"?** **Recomiendo solo correo y
   formulario web**, porque la respuesta vuelve al buzón. Chat, messaging, API y desconocido no
   cuentan. Los chats de Zendesk o Gorgias pasarían a `status_only` o al OTP.
3. **¿El OTP entra en el piloto o sigue post-piloto (decisión s79)?** **Recomiendo meterlo en
   el Sprint 3, junto al widget.** En el widget el invitado es el caso normal, y sin OTP solo
   vería el estado de sus pedidos y cualquier otra cosa acabaría en una persona. Son un PR y una
   tabla, y Postmark ya está casi listo.
4. **¿Canal del OTP en la v1?** **Recomiendo solo email por Postmark.** El teléfono (plantilla
   `AUTHENTICATION` de WhatsApp) cuando un tenant tenga pedidos solo con teléfono.
5. **¿Default de las L3: `sender` (como hoy) o `strong` (siempre OTP)?** **Recomiendo `sender`
   más la aprobación humana mostrando el método**, y `strong` como opción por tenant. Con
   aprobación humana en todas las L3, exigir OTP siempre añade fricción sin cambiar quién decide.
6. **¿Firma del widget: App Proxy de Shopify o JWT propio?** **Recomiendo App Proxy** para
   tiendas Shopify, porque el comerciante no programa nada. Se confirma en el spike de #258, y
   el JWT queda para webs que no sean Shopify.
