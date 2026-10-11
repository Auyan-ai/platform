# ADR 0012 — Escritura natural por canal: el código pone el formato, el LLM las palabras

**Estado:** Propuesta
**Fecha:** 2026-10-11

## Contexto

El agente al cliente final escribía como un bot:

- La regla global "Formato" decía "tus respuestas se muestran en una ventana de chat" para
  TODOS los canales y permitía viñetas. El texto del propio prompt estaba lleno de `**negrita**`,
  y el modelo imita lo que lee.
- Zendesk envía las respuestas como `comment.body` en texto plano: los `**` llegaban
  literales al correo del cliente. WhatsApp convertía el Markdown a su marcado (`*x*`, `•`),
  que también se ve como un asistente y no como una persona.
- Un correo no es un chat: faltaba saludo, párrafos y firma. Y el LLM, cuando firmaba, lo
  hacía con un nombre inventado o distinto en cada respuesta.
- Nada de esto se podía comprobar: "escribe natural" era una petición al modelo sin
  garantía ni métrica.

Restricciones de producto:

- La voz de cada marca (tono, tú o usted, emojis, vocabulario, personalidad) es del tenant.
  El canal no puede pisarla.
- Regla dura: **código sobre LLM**. Todo lo que pueda ser determinista es código con tests.
  El LLM hace solo lo que hace mejor que el código: la redacción y el registro.

## Decisión

Tres capas, cada una con un dueño distinto.

| Capa | Quién | Qué decide |
|------|-------|------------|
| Superficie de escritura (`chat`, `whatsapp`, `email`) | Código (`services/writing_surface.py`) | A qué superficie va la respuesta |
| Normalizador y firma | Código (`services/reply_format.py`) | Sin Markdown ni marcado de WhatsApp, sin emojis salvo opt-in, viñetas sin símbolo, despedida del LLM fuera y firma de correo añadida |
| Redacción y registro | LLM (prompt) | Tono, trato, vocabulario, longitud dentro del canal, saludo y cierre breve en correo |

**Superficie.** `whatsapp` → whatsapp; `chat`/`widget`/`instagram`/`intercom` → chat; `email` → email.
En los helpdesk (Zendesk, Gorgias, Chatwoot) depende del origen del ticket. El intake guarda
el campo del proveedor en `messages.metadata.source_channel` (Zendesk `via.channel`,
Gorgias `message.channel`, Chatwoot `conversation.channel`) y se lee el del último mensaje
del cliente. Origen de chat o mensajería → chat. Email, formulario web, API, centro de
ayuda, desconocido o ausente → email: un saludo y una firma de más no rompen nada, un
registro de chat en un correo sí se nota. No hay migración: la superficie se deriva del
metadata del mensaje.

**Normalizador.** Un único punto, `finalize_agent_reply`, lo llaman los dos nodos que
persisten el mensaje al cliente (`respond` y `escalate`) y devuelven el texto final como
`agent_response`. Lo guardado en `messages` es exactamente lo que recibe el cliente. El
adapter de WhatsApp conserva el troceado y aplica la misma limpieza (idempotente).

- Fuera: negrita y cursiva, encabezados, tablas, bloques de código, citas, reglas, HTML y
  el marcado de WhatsApp. Un enlace `[texto](url)` pasa a `texto: url` al final de línea y
  a `texto (url)` a mitad de frase.
- Emojis fuera salvo `tenant_config.extra["allow_emojis"] is True`.
- Viñetas: se quita el símbolo y cada elemento queda en su propia línea. Las listas
  numeradas se respetan. Es lo que escribiría una persona en un chat o correo sin editor
  enriquecido, y no inventa un símbolo propio.
- Nunca se alteran números, ids de pedido, emails, URLs ni importes: URLs y emails se
  protegen durante la limpieza y hay tests con casos adversarios.

**Firma (solo `email`).** El código quita una despedida final del LLM (lista corta de
fórmulas en línea propia, más un nombre corto debajo; conservador) y añade
`\n\n{firma}`. La firma es `tenant_facts.email_signature` si existe; si no, `El equipo de
{company_name}` y, en su defecto, el nombre del tenant. `email_signature` no se inyecta
en el prompt, para que el modelo no firme por su cuenta. El cliente la edita en el
dashboard (campo "Firma de correo").

**Prompt.** La regla global pasa a ser agnóstica al canal (prosa natural, sin símbolos de
Markdown, sin emojis salvo que la voz de marca los pida, directo) y se quita el `**`
decorativo del texto del prompt. El registro por canal va en el bloque volátil del turno
(unas líneas), nunca en el bloque cacheado del AOP: la clave de caché
`(tenant, slug, workspace)` no cambia. Precedencia explícita: la voz de marca decide tono,
trato, emojis y vocabulario; las reglas del canal deciden formato, longitud y estructura.

**Métrica.** `has_markdown` y `has_emoji` son deterministas y comparten implementación con
el normalizador. El transcript del slow agent incluye el recuento de respuestas con
Markdown o emojis, y el judge tiene un criterio de naturalidad para el canal.

## Consecuencias

- Buenas: el formato deja de depender del modelo; la firma es siempre la misma; el
  historial refleja lo entregado; hay una métrica y tests para el comportamiento que antes
  era solo un deseo. Ningún cambio de esquema.
- Un tenant cuya voz de marca pida emojis necesita además `allow_emojis: true`. Sin el
  flag, el código los quita aunque el prompt los permita. Es deliberado: el opt-in es un
  dato explícito y comprobable, no una interpretación del texto de la voz.
- Los mensajes fijos de otros caminos (acuses de WhatsApp, tope de mensajes, iteraciones
  agotadas) no pasan por `respond` ni `escalate`; WhatsApp los limpia en el adapter, el
  resto se mantiene como texto de código ya limpio.
- Los tickets de helpdesk anteriores a este cambio no tienen `source_channel` y se tratan
  como email hasta el siguiente mensaje del cliente.
- La eliminación de despedidas es heurística: puede dejar pasar una fórmula rara (se
  vería una despedida doble) pero está acotada para no cortar contenido.
- El normalizador pierde estructura que el cliente a veces agradecería (una tabla de
  tres pedidos). Aceptado: un agente que escribe como una persona gana más que lo que
  pierde, y la regla del prompt pide una línea por dato.
