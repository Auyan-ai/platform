# ADR 0015 — De la URL de la tienda al agente: un motor de ingesta para demos y onboarding

**Estado:** Propuesta (pasa a Aceptada cuando se mergee la implementación)
**Fecha:** 2026-10-25 (sesión 87)
**Relación:** alimenta la KB, `tenant_facts` y `tenant_playbook`, y deja un borrador de la
política de [ADR 0014](0014-devoluciones-y-cambios-politica-del-tenant.md) sin saltarse su
regla de "sin valores por defecto". La ingesta usa una cola con lease como la de
[ADR 0008](0008-inbound-queue-postgres.md). Retoma el modo gestionado de
[#353](https://github.com/Auyan-ai/platform/issues/353); el self-serve sigue fuera.
Plan de ejecución: [`url-to-agent-plan.md`](../url-to-agent-plan.md).

## Contexto

Hoy el conocimiento entra a mano. El cliente pega texto en el wizard y Auyan lo aprueba. Una
submission de tipo `url` no se descarga: `Step6Kb.tsx` y `KbUploadStep.tsx` guardan la URL
como contenido, y al aprobarla entra al RAG el texto `https://…`. La API de la KB solo
inserta: no lista, no sustituye y no borra documentos (solo `seed_kb --clear` borra en
blando). Lo que cambia en la web queda viejo. En staging, Marea tiene un único documento
pegado a mano.

Para el piloto necesitamos dos cosas con la misma pieza:

- **Demo:** con la URL de un prospecto, un agente que responde con los datos reales de su
  tienda en pocos minutos.
- **Onboarding:** si el prospecto firma, esa demo es el punto de partida del tenant real. No
  se rehace nada.

Chatbase hace lo primero con un crawl genérico (home, sitemap o URLs sueltas) y saca marca y
tono de la web. No configura políticas ni acciones.

### Lo que midió el prototipo (sesión 87)

Contra 7 tiendas Shopify públicas de España (Singularu, Ecoalf, Scalpers, Thinking Mu, Saigu,
Oh My Cream, Alohas) y 3 que no son Shopify (Nude Project, Mimitos, Hawkers), con un
User-Agent que se identifica como bot:

| Fuente | Resultado |
|---|---|
| HTML de tiendas Shopify | 6 de 7 devuelven 429 desde la primera petición. Shopify exige [Web Bot Auth](https://shopify.dev/docs/api/storefront#identifying-bots-with-web-bot-auth), una firma que crea la tienda en su admin. |
| HTML de webs que no son Shopify | Funciona. Mimitos dio 22 páginas y Hawkers 41. Nude Project no tiene sitemap. |
| Storefront API de Shopify sin token (`/api/<versión>/graphql.json`) | Funciona en todas. Da las políticas completas (Alohas, 1.139 palabras de devoluciones), las páginas con su texto y el catálogo. Las páginas montadas con secciones del tema salen vacías. |
| Storefront MCP (`/api/mcp`, `search_shop_policies_and_faqs`) | Funciona. Solo aporta si la tienda rellenó su FAQ en Shopify (Singularu, 11 de 18 preguntas). El resto, 4 de 18 respuestas genéricas. |
| `llms-full.txt` y `agents.md` | Shopify los genera en todas las tiendas, pero el texto por defecto son instrucciones de compra por UCP. Solo vale el que la tienda reescribió (Scalpers, 2.096 palabras con hechos, FAQ y tono). |
| Admin API con el token de Marea | Los scopes no incluyen `read_content`. No hace falta: la Storefront API pública da lo mismo. |

Con la Storefront API, la página de envíos y la de devoluciones, las 4 tiendas medidas
cubren de 8 a 10 de los 10 datos clave (plazo de devolución, email, teléfono, horario, envío
gratis, coste y plazo de envío, pagos, cambios, tiendas físicas). La extracción con LLM no se
midió: el saldo de Anthropic de staging estaba a cero (#371).

## Decisión

**Un solo motor, `services/site_ingestion/`, convierte la URL pública de una tienda en
documentos de KB revisables y en borradores con cita. Lee primero las fuentes oficiales de la
plataforma y después el HTML que el sitio nos sirva como bot identificado. Una demo es un
tenant con `origin = 'demo'` y sin admin. Convertirlo en cliente le añade el admin al mismo
tenant.**

### 1. Acceso: bot identificado, sin evasión

User-Agent `AuyanBot/<versión> (+https://auyan.es/bot)`, con una página pública que explica
qué leemos y cómo bloquearnos. Se respeta `robots.txt`. Ante un 429 se espera lo que diga
`Retry-After` (o un back-off exponencial) y, si se repite, se abandona esa fuente y se anota.
No se falsea el User-Agent, no se usan proxies residenciales ni servicios que esquiven la
protección anti-bots. Lo que la tienda no nos sirve no se lee.

Para un cliente Shopify que quiera las páginas montadas con secciones, el onboarding le pide
crear una firma Web Bot Auth para Auyan. Es opcional y llega en una fase posterior.

### 2. Fuentes, en este orden

| Orden | Fuente | Qué aporta | Plataforma |
|---|---|---|---|
| 1 | Storefront API sin token: `shop`, políticas, `pages`, blogs y artículos | Políticas y páginas oficiales, nombre y descripción | Shopify |
| 2 | Storefront MCP `search_shop_policies_and_faqs` con una batería fija de preguntas de CX | FAQ que la tienda cargó en Shopify. Se descartan las respuestas genéricas conocidas | Shopify |
| 3 | `llms-full.txt`, `llms.txt`, `agents.md` | Solo si no es la plantilla por defecto de Shopify | Todas |
| 4 | `sitemap.xml` (desde `robots.txt`), o enlaces de la home si no hay sitemap → páginas clave por patrón de ruta → contenido principal a markdown con trafilatura | El resto: FAQ, contacto, tallas, tiendas | Todas, si el sitio lo sirve |
| 5 | Catálogo (Storefront API) | No va a la KB. Alimenta la skill de producto en la demo con precio y stock por talla en tiempo real | Shopify |
| 6 | Tickets históricos del helpdesk del cliente (Zendesk, Gorgias, Chatwoot) | Las preguntas reales de sus clientes con la respuesta de su equipo. Es lo que tapa el hueco del FAQ | Solo clientes, con el helpdesk conectado |

Tope por ingesta: 60 páginas, 150 peticiones y 2 peticiones simultáneas por dominio. Cada
fuente tiene una **clave canónica** (`source_key`): la URL sin esquema, sin `www`, sin barra
final y sin query; la URL de la política que devuelve la Storefront API; y
`mcp:faq/<pregunta>` para las respuestas del MCP. Se guarda con el tipo, el hash SHA-256 del
texto normalizado y la fecha de lectura.

### 3. KB: una fuente es un documento, y se puede sustituir

- `knowledge_base_documents` gana `source_key` y `content_sha256`. La migración rellena
  `source_key` desde `source` cuando es una URL. Índice único parcial de
  `(tenant_id, source_key)` entre los documentos vivos.
- Como mucho hay **una submission pendiente por `(tenant_id, source_key)`**: una más nueva
  sustituye a la pendiente (`superseded`). Reingestar con el mismo hash que el documento vivo
  no crea nada.
- Al aprobar se bloquea con `FOR UPDATE` el documento vivo de esa clave, se borra en blando y
  se inserta el nuevo en la misma transacción. Dos aprobaciones de la misma clave no pueden
  dejar dos documentos.
- `knowledge_base_chunks` gana `deleted_at`. El borrado en blando de un documento marca sus
  chunks. La búsqueda filtra los chunks borrados dentro del escaneo HNSW con el escaneo
  iterativo de pgvector 0.8 (`hnsw.iterative_scan`), para que los chunks muertos no ocupen el
  `top_k`.
- Las submissions de una ingesta comparten `ingestion_id`. La cola de revisión aprueba el lote
  entero o quita fuentes sueltas.
- El troceo respeta los encabezados del markdown y cada chunk lleva el título de su sección.
  Los embeddings se piden por lotes.
- API de super_admin para listar y borrar en blando documentos de la KB.
- Aprobar una submission `url` cuyo contenido es solo la URL devuelve 400.

### 4. Borradores con cita, verificada en código

Un LLM (Sonnet, según el routing de ADR 0007) lee las fuentes y rellena un esquema Pydantic.
Cada valor lleva `source_id` y una cita literal. **El código comprueba que la cita aparece en
la fuente**, con espacios normalizados. Un valor sin cita verificable se descarta. Las
contradicciones entre fuentes se guardan y se muestran.

Los borradores viven en una tabla propia, `site_extractions`: una fila por campo y destino,
con `tenant_id`, `ingestion_id`, `target` (`facts`, `playbook` o `returns_policy`), `field`,
`value jsonb`, `source_key`, `quote`, `status` (`proposed`, `applied_unconfirmed`,
`confirmed` o `rejected`), timestamps, `deleted_at` y RLS. No se escriben en
`tenant_returns_policies`: allí la última fila es la política vigente, y un borrador parcial
no valida contra `ReturnsPolicy`.

| Destino | Qué rellena | Cómo se aplica |
|---|---|---|
| `tenant_facts` | Nombre, email, teléfono, horario, web, envíos, pagos, tiendas físicas | Diff contra lo actual, con la fuente de cada campo; se aplica campo a campo y se fusiona con lo que hay |
| `tenant_playbook` | `brand_voice` (con citas de cómo escribe la tienda) y `product_overview` | El equipo lo revisa y guarda |
| `ReturnsPolicy` (ADR 0014) | Solo los campos que la web dice: plazo y desde cuándo cuenta, cambios, quién paga la vuelta, cómo se reembolsa, artículos excluidos | **Nunca se activa solo.** El formulario de la política se abre prellenado desde `site_extractions` y la tienda lo guarda con el validador de siempre |

### 5. Demo: un tenant con `origin = 'demo'`

- `tenants` gana `origin` (`client` por defecto, o `demo`) y `demo_expires_at`. El slug de una
  demo es `demo-<tienda>-<sufijo aleatorio>`, porque el slug es único incluso entre tenants
  borrados.
- La demo se crea con la parte del alta que no depende del admin (configuración, prompt base,
  fila de onboarding y AOPs canónicos), en lifecycle `initial`, sin canales y solo con skills
  L1.
- `origin = 'demo'` se excluye de todo lo que trata con tenants reales: el intake de webhooks
  la rechaza (el lifecycle no bloquea nada en runtime), y quedan fuera los informes semanales,
  la cola de revisión de conocimiento y la resincronización.
- En la demo, las fuentes y los valores con cita verificada se aplican solos, con estado
  `applied_unconfirmed`. La política de devoluciones sigue sin activarse.
- **Probar agente:** un chat en la ficha del tenant. Cada sesión es una conversación
  `is_simulation` con su fila en `simulation_runs`, así cuenta en el tope de gasto del
  simulador (#372) y queda fuera de las métricas del cliente (#359). Corre el grafo real,
  trazado en LangSmith. El estado del turno lleva un modo de adaptador de comercio:
  `live`, `mock` (simulador con fixtures) o `demo_catalog`, que es un adaptador de solo lectura
  sobre la Storefront API pública para la skill de producto. Las preguntas de pedidos escalan
  con razón explícita.
- El job de limpieza borra en blando las demos caducadas. Por defecto caducan a los 30 días.

### 6. Convertir la demo en cliente

El alta actual (`tenant_provisioning`) solo crea tenants nuevos. Se separa en dos piezas
idempotentes: `scaffold_tenant` (lo que usa también la demo) y `attach_tenant_admin` (el
usuario de auth, la fila de `users`, la asignación y la invitación). El alta de siempre las
llama en orden. "Convertir en cliente" llama solo a `attach_tenant_admin` sobre la demo,
cambia `origin` a `client`, renombra el slug, pasa a `discovery` y quita la caducidad.

Se conservan la KB, los datos, el playbook y los borradores. Para que eso sea verdad:

- `POST /me/onboarding/submit` fusiona lo que trae el wizard con lo que hay y nunca deja en
  blanco un campo que ya tenía valor. Hoy sobrescribe `tenant_playbook` y `tenant_facts`.
- Lo que la demo aplicó sin revisar (`applied_unconfirmed`) se lista en el checklist del
  cliente. El tenant no pasa a `shadow` ni a `active` hasta que cada valor y el lote de la KB
  están confirmados o rechazados.
- El gate de conocimiento del checklist cuenta solo submissions aprobadas. Hoy cuenta
  cualquiera, también las rechazadas.

### 7. Ejecución, coste y trazas

`site_ingestions` es una cola con lease como `inbound_jobs`: `status` (`queued`, `fetching`,
`extracting`, `ready` o `failed` con causa), `attempts`, `locked_until` y un índice único
parcial que permite una sola ingesta no terminada por tenant. La procesa un worker en el
proceso del API, y el parseo de HTML corre en `asyncio.to_thread` para no bloquear los turnos
inbound en la única instancia de Cloud Run.

Cada ingesta queda en LangSmith con las fuentes leídas y descartadas, los tokens y el coste.
`site_ingestions` guarda `cost_usd` y `langsmith_trace_id` para correlacionar con Supabase. El
coste **no** entra en `tenant_usage_daily`: una resincronización no puede agotar el
presupuesto del tenant y bloquear sus turnos reales. Hay un tope por ingesta y otro diario
global.

### 8. Contenido con fecha

La extracción marca las frases con fecha de fin ("Envío gratis hasta el 1/11") como
`time_bound` con su `valid_until`. Pasada la fecha, sus chunks dejan de recuperarse y el
valor de `site_extractions` pasa a `expired`, sin esperar a la resincronización. Un agente que
sigue prometiendo una promo caducada responde mal en nombre de la tienda.

### 9. FAQ desde los tickets del helpdesk

Con el helpdesk del cliente conectado, se leen sus tickets cerrados, se agrupan las preguntas
repetidas y se propone cada par pregunta y respuesta como submission `pending_review`, con
cita al ticket de origen. Se quitan los datos personales antes de guardar (`services/pii.py`).
Llega como borrador revisable, igual que el resto.

### 10. Resincronización

Un bucle del lifespan del API, como el de limpieza, reingesta cada semana los tenants con
`origin = 'client'`, `status = 'active'` y `agent_lifecycle_state` en `shadow`, `ramping` o
`active`. Lo que no cambió se ignora por hash. Lo que cambió abre submissions y avisa al
equipo, porque una política que cambia en la web y no en el agente es una respuesta incorrecta
al cliente final.

### 11. Cómo llega el conocimiento al agente: KB entera o búsqueda

Anthropic recomienda no usar RAG cuando la base de conocimiento cabe en el prompt (menos de
unos 200.000 tokens) y meterla entera con prompt caching ([Contextual
Retrieval](https://www.anthropic.com/news/contextual-retrieval)). La KB de una tienda ocupa
10-20k tokens (Thinking MU: 6.950 palabras en 9 fuentes oficiales).

Medido en la sesión 87 (#410): con la búsqueda de entonces (top 5 y similitud mínima 0,6),
el agente recuperaba la respuesta en 6 de 12 preguntas con dato sobre Thinking MU, y en las 6
restantes no recibía ningún fragmento. En staging, 380 de 394 turnos de Marea en 60 días no
recuperaron nada. Sin umbral y con top 20, 12 de 12; con la KB entera, 12 de 12.

- **El modo se elige en código**, con una función pura: `full_context` si el tamaño estimado
  de los documentos vivos cabe en el presupuesto, `retrieval` si no. El presupuesto por
  defecto es 50.000 tokens, configurable por tenant: por debajo del límite de Anthropic porque
  cada turno hace varias llamadas al LLM y el contexto largo degrada el recuerdo del modelo.
  La estimación es determinista sobre el texto (sin llamar a Anthropic) y conservadora.
- **En `full_context`**, la KB va como bloque propio del system, cacheado y antes del AOP
  (que cambia según el intent), con el título y la URL de cada documento para poder citar.
- **En `retrieval`**, top 20 sin umbral y consulta construida con los últimos mensajes del
  cliente, no solo con el último. Contexto por fragmento, BM25 y reranking quedan para cuando
  haya un tenant con KB grande que lo necesite.
- Cada turno registra el modo, el tamaño estimado y el número de documentos en LangSmith y en
  los eventos de razonamiento.

## Alternativas descartadas

| Opción | Por qué no |
|---|---|
| Crawl de HTML genérico, como Chatbase | En Shopify, 6 de cada 7 tiendas no se lo sirven a un bot identificado. El HTML crudo es casi todo menú y pie (una página de 688 KB tenía 94 palabras de política entre 837). |
| Hacerse pasar por navegador o usar un servicio que esquive la protección anti-bots | Va contra lo que piden las propias tiendas y Shopify, y nos expone legal y comercialmente justo con quien queremos vender. |
| Admin API como fuente principal | Exige token y scopes (Marea no tiene `read_content`), así que no vale para una demo. La Storefront API pública da el mismo contenido. |
| Una tabla nueva de "workspaces de demo" | Habría que migrar los datos al convertir. Un tenant con `origin = 'demo'` no se migra: cambia de estado. |
| Reutilizar el simulador tal cual para "Probar agente" | El simulador es un bucle con un cliente sintético de Haiku y siempre inyecta el mock de Shopify. La demo necesita que escriba una persona y un catálogo real. |
| Imputar el coste de la ingesta a `tenant_usage_daily` | Una resincronización podría disparar `check_tenant_budget` y cortar turnos reales. |
| Aplicar los borradores sin revisión en un tenant real | El agente le habla a clientes finales. Un dato mal extraído es una respuesta incorrecta firmada por la tienda. |
| Rellenar la política de devoluciones con lo que "suele" hacer el sector | Lo prohíbe ADR 0014: sin política explícita, el agente no actúa y escala. |

## Consecuencias

- La demo y el onboarding comparten código y datos: lo que se ve en la demo es lo que recibe
  el cliente, y lo que no se revisó no llega a clientes finales.
- La KB pasa a tener ciclo de vida: sustituir, borrar y resincronizar.
- El alta de tenants se parte en dos piezas, y el envío del wizard deja de sobrescribir.
- En tiendas Shopify sin firma Web Bot Auth, el contenido que solo está en secciones del tema
  no entra. El informe de la ingesta lo dice y el onboarding lo pide.
- Cada respuesta del agente que use la KB se puede rastrear hasta una URL de la tienda.
- Gasto nuevo de LLM por ingesta, con su propio libro de costes (estimado: unos céntimos por
  tienda con Sonnet y menos de 20.000 palabras de fuentes; está pendiente de medir).
- Se publica `auyan.es/bot`.

## Apéndice: comparación con Chatbase (25-oct-2026, Thinking MU)

Kenny creó un agente en Chatbase con la URL de Thinking MU y le hizo la batería de preguntas
de `url-to-agent-plan.md`.

- **El onboarding con la URL no carga conocimiento.** Escribe las instrucciones (contexto del
  negocio, rol, idioma, restricciones) y deja la KB con 0 fuentes. Sin crawl, no sabía el
  envío a Canarias.
- **Su crawler pasa el bloqueo de Shopify con un Chrome headless.** Encontró 3.968 enlaces y
  entrenó las 120 páginas elegidas sin ningún "Not found". En el contenido guardado aparecen
  errores de Chrome (`ERR_BLOCKED_BY_CLIENT`, "blocked by an extension"), y ofrece elegir el
  país desde el que se hacen las peticiones.
- **Aun así no consigue el FAQ.** Muchas páginas pesan exactamente 13 KB, y `ayuda-pedido` es
  solo plantilla: selector de país, carrito, productos recomendados, login y cookies. `/pages`
  ocupa 2 MB, casi todo ruido.
- **Responde bien.** Acertó las 6 preguntas con datos en la web, detectó la contradicción
  de Portugal (3,90 € y 6,90 €) y no inventó en Klarna, tallas ni pedidos. La promo "envío
  gratis hasta el 1/11" la repite, y sin resincronizar (función de pago) quedará vieja.
- **Acciones de Shopify** ([documentación](https://www.chatbase.co/docs/user-guides/chatbot/actions/shopify-actions)):
  estado de pedido, carrito, crear pedidos, cambios y devoluciones. La devolución usa un plazo
  de 30 días por defecto y no pide aprobación. No cancela pedidos ni cambia la dirección de
  envío de un pedido: ante "Quiero cancelar mi pedido" manda a escribir al email de la tienda.

Conclusión: leer el HTML de Shopify saltándose la protección anti-bots no aporta el contenido
que falta. Nuestra demo se mide con la misma batería y tiene que sacar al menos lo mismo. La
diferencia está en el catálogo en tiempo real, los datos con cita, la detección de cambios y
las acciones con dinero (cancelar, cambiar dirección, devolver según la política de la tienda
y con aprobación).
