# Plan: de la URL al agente (ADR 0015)

Con la URL pública de una tienda, el equipo levanta en minutos una demo que responde con los
datos reales de esa tienda. Si el prospecto firma, la demo se convierte en su tenant y el
onboarding arranca con la KB, los datos y la voz de marca ya cargados. Regla para todo el
plan: cada dato que llega al agente lleva su URL de origen y una cita verificada en código, y
nada que no se haya revisado llega a un cliente final.

Cada PR va contra `develop` con su sección "Evidencia en vivo" de `/verify` y se verifica por
separado. Orden y dependencias:

| PR | Qué | Depende de |
|---|---|---|
| 0 | Página pública del bot | Nada |
| 1 | Ciclo de vida de la KB | Nada |
| 2a | Arreglar la recuperación de la KB (#410): sin umbral, top 20, consulta con la conversación | PR 1 |
| 2b | KB entera en contexto cuando cabe, con selector automático (ADR §11) | PR 2a |
| 2 | Troceo por secciones y embeddings por lotes (solo afecta a KBs grandes; baja de prioridad) | PR 2b |
| 3 | Motor de ingesta, sin LLM | PR 0, PR 1 |
| 4 | Revisión por lotes | PR 3 |
| 5 | Borradores con cita | PR 3 y saldo de Anthropic (#371) |
| 6 | Alta en dos piezas y wizard que fusiona | Nada |
| 7 | Crear una demo desde una URL, con caducidad | PR 4, PR 5, PR 6 |
| 8 | Catálogo en tiempo real para la demo | Nada |
| 9 | Probar agente, medido con la batería | PR 7, PR 8 |
| 10 | Convertir la demo en cliente | PR 7 |
| 11 | Resincronizar cada semana | PR 4 |
| 12 | FAQ desde los tickets del helpdesk | PR 4 |

PR 0, PR 1, PR 6 y PR 8 son independientes y pueden ir en paralelo.

## Cómo se sabe que funciona

Estas metas se fijan antes de construir. Se miden en el PR que corresponde y se repiten al
final con las tiendas de referencia.

| Meta | Cómo se mide | Umbral |
|---|---|---|
| Tiempo de URL a demo lista | Del `POST` hasta `ready`, en Cloud Run de staging | p50 ≤ 3 min, p95 ≤ 6 min |
| Precisión de los borradores | Gold set: 5 tiendas × 17 campos etiquetados a mano desde las fuentes | ≥ 95 % de los valores mostrados son correctos |
| Cobertura de los borradores | Mismo gold set | ≥ 70 % de los campos que la fuente sí dice |
| Citas | Valores mostrados cuya cita aparece en la fuente | 100 % (lo garantiza el código) |
| Calidad de la KB | 20 preguntas reales de CX por tienda en el simulador, con el judge | La KB automática resuelve ≥ 80 % de lo que resuelve la curada a mano (Marea) |
| Demo frente a Chatbase | Batería del apéndice sobre Thinking MU | Al menos lo que sacó Chatbase, sin inventar en las preguntas sin dato, y con cancelación y cambio de dirección como flujo con aprobación |
| Coste por ingesta | `site_ingestions.cost_usd` y LangSmith | ≤ 0,25 USD por tienda |
| Cortesía con el sitio | Peticiones por ingesta y 429 recibidos | ≤ 150 peticiones; ningún reintento sin respetar `Retry-After` |

Tiendas de referencia: Thinking Mu, Ecoalf, Alohas y Singularu (Shopify), y Mimitos (no
Shopify). En staging, el tenant `thinkingmu-prueba` tiene la KB de Thinking MU cargada desde
sus 9 fuentes oficiales (41 chunks) y es donde se mide la batería del apéndice. Marea solo sirve para el camino de "convertir en cliente": su tienda tiene
contraseña.

## PR 0. Publicar la página del bot

- [ ] Crear `apps/landing/app/bot/page.tsx`: qué es AuyanBot, qué lee, que respeta
  `robots.txt` y cómo bloquearlo (`User-agent: AuyanBot`).
- [ ] Verificar: `curl -I https://auyan.es/bot` devuelve 200. Tiene que estar publicada antes
  del primer crawl en vivo del PR 3, también en staging.

## PR 1. Dar ciclo de vida a la KB

- [ ] Migración: `knowledge_base_documents.source_key` y `content_sha256`, relleno de
  `source_key` desde `source` cuando es una URL, e índice único parcial
  `(tenant_id, source_key)` entre los documentos vivos.
- [ ] Migración: `knowledge_base_chunks.deleted_at`. El borrado en blando de un documento marca
  sus chunks.
- [ ] `search_knowledge_chunks`: filtrar los chunks borrados dentro del escaneo HNSW con
  `SET LOCAL hnsw.iterative_scan = relaxed_order` (pgvector 0.8.0 en staging).
- [ ] Aprobar: `FOR UPDATE` sobre el documento vivo de la misma clave, borrado en blando y
  alta del nuevo en una transacción.
- [ ] Una sola submission pendiente por `(tenant_id, source_key)`: la nueva marca la anterior
  como `superseded`.
- [ ] `GET` y `DELETE` (borrado en blando) de documentos de la KB para `super_admin`.
- [ ] Aprobar una submission `url` cuyo contenido es solo la URL devuelve 400. `Step6Kb.tsx` y
  `KbUploadStep.tsx` dejan de copiar la URL al contenido.
- [ ] El gate `has_knowledge` del checklist cuenta solo submissions aprobadas.
- [ ] Web: la cola de revisión muestra los documentos indexados y permite borrarlos.
- [ ] Unit: dos aprobaciones de la misma clave dejan un documento vivo; los chunks de un
  documento borrado no salen en la búsqueda aunque sean los más parecidos; una URL sin
  contenido da 400; una submission rechazada no cuenta para el checklist.
- [ ] Vivo (`/verify`, staging): aprobar, sustituir y borrar un documento en Marea. Un turno del
  agente deja de recuperar el chunk borrado.

## PR 2a. Arreglar la recuperación de la KB (#410)

- [ ] `rag_top_k = 20` y `rag_min_similarity = 0.0` por defecto.
- [ ] La consulta del embedding usa los últimos 3 mensajes del cliente, no solo el último.
- [ ] Vivo: medición sobre `thinkingmu-prueba` en staging, de 6/12 a 12/12.

## PR 2b. Meter la KB entera cuando cabe

- [ ] `choose_knowledge_mode(total_tokens, budget)` pura; presupuesto 50.000 por defecto,
  configurable por tenant.
- [ ] En `full_context`, sin embeddings ni búsqueda: la KB entera como bloque cacheado antes
  del AOP, con título y URL por documento. Las demás llamadas que hoy reciben fragmentos
  (supervisor, judge) usan la misma fuente.
- [ ] Modo, tamaño y número de documentos en LangSmith y en los eventos de razonamiento.
- [ ] Vivo sin LLM: los bloques del system reales de `thinkingmu-prueba` y `marea-studio`.
- [ ] Vivo con saldo de Anthropic: la batería del apéndice antes y después.

## PR 2. Trocear por secciones y pedir embeddings por lotes

Cambia lo que recupera el agente de todos los tenants, así que va solo y con su medida.

- [ ] `chunk_text_for_kb` respeta encabezados markdown y antepone el título de sección.
- [ ] `embed_kb_chunks` pide los embeddings por lotes.
- [ ] Script que reindexa los documentos de un tenant con el troceo nuevo.
- [ ] Medir en Marea antes y después: 20 preguntas del simulador, chunk correcto en el top 5 y
  similitud del primero. No se mergea si empeora.
- [ ] Unit: una sección corta no se parte; una larga se parte con solape y conserva su título.

## PR 3. Leer la web de la tienda (motor de ingesta, sin LLM)

- [x] Migración `site_ingestions` como cola con lease: `tenant_id`, `root_url`, `platform`,
  `status` (`queued`, `fetching`, `extracting`, `ready`, `failed`), `failure_reason`,
  `attempts`, `locked_until`, `stats jsonb`, `cost_usd`, `langsmith_trace_id`, timestamps,
  `deleted_at`, RLS e índice único parcial de una ingesta no terminada por tenant.
- [x] `services/site_ingestion/fetcher.py`: User-Agent de AuyanBot, `robots.txt`, 2 peticiones
  por dominio, `Retry-After`, tope de 60 páginas y 150 peticiones.
- [x] `services/site_ingestion/sources/`: un módulo por fuente del ADR. Cada uno devuelve
  `SourceDoc(source_key, url, kind, title, markdown, sha256)`. Se descartan la plantilla por
  defecto de `llms-full.txt` y las respuestas genéricas del MCP.
- [x] Parseo de HTML con trafilatura en `asyncio.to_thread`.
- [x] Orquestador: deduplica por hash y crea submissions `pending_review` con `ingestion_id`.
- [x] Worker en el lifespan que reclama jobs con lease, y endpoints
  `POST /tenants/me/site-ingestions` y `GET .../{id}`.
- [x] Script `scripts/ingest_site.py --tenant <slug> --url <url> [--dry-run]`.
- [x] Unit con respuestas grabadas de tiendas reales (`httpx.MockTransport`): Storefront API
  de Thinking Mu, sitemap de Mimitos, 429 con `Retry-After`, `robots.txt` que bloquea, lease
  expirado que se vuelve a reclamar.
- [ ] Vivo: ingestar las 5 tiendas de referencia en un tenant de pruebas de staging (hecho en
  `--dry-run`, sin base; la ingesta real espera a aplicar la migración en staging). Anotar
  fuentes, palabras, peticiones, 429 y segundos de cada una. Un turno inbound que llega durante
  una ingesta no se retrasa.
- [x] Reingestar la misma tienda no crea ninguna submission.

## PR 4. Revisar una ingesta por lotes

- [ ] `POST .../site-ingestions/{id}/approve` con la lista de fuentes excluidas. Aprueba e
  indexa el resto en una sola operación.
- [ ] Web: la ficha del tenant muestra la ingesta (fuentes leídas, descartadas y bloqueadas por
  el sitio) con casillas para quitar fuentes.
- [ ] Vivo: ingestar Thinking Mu, quitar una fuente y aprobar el lote. El agente responde en el
  simulador el plazo de devolución citando la página correcta.

## PR 5. Borradores con cita

- [ ] Migración `site_extractions` (ADR 0015 §4), con RLS.
- [ ] `services/site_ingestion/extract.py`: esquema Pydantic con cita obligatoria. Sonnet con
  tool use. Verificación literal de la cita en código y descarte de lo que no verifica.
- [ ] Destinos: `tenant_facts` (fusión campo a campo), `tenant_playbook.brand_voice` y
  `product_overview`, y el borrador de la política de devoluciones, que solo prellena el
  formulario.
- [ ] Contenido con fecha (ADR §8): `time_bound` y `valid_until` en la extracción. Pasada la
  fecha, sus chunks no se recuperan y el valor pasa a `expired`. Unit con el banner real de
  Thinking MU ("Envío gratis hasta el 1/11").
- [ ] Web: diff campo a campo con la URL y la cita, y aplicar o rechazar por campo.
- [ ] Eval en `apps/api/evals/site_extraction/`: gold set de 5 tiendas × 17 campos con su
  script. Falla si la precisión baja del 95 %.
- [ ] Coste en `site_ingestions.cost_usd`, traza en LangSmith, tope por ingesta y diario global.
- [ ] Vivo: correr la extracción en las 5 tiendas y adjuntar la tabla de precisión, cobertura y
  coste.

## PR 6. Partir el alta en dos piezas y hacer que el wizard fusione

- [ ] `tenant_provisioning`: separar `scaffold_tenant` (configuración, prompt base, onboarding,
  AOPs canónicos) y `attach_tenant_admin` (usuario de auth, `users`, asignación e
  invitación). Las dos son idempotentes. El alta de siempre llama a las dos.
- [ ] `POST /me/onboarding/submit` fusiona con `tenant_playbook` y `tenant_facts` y nunca deja
  en blanco un campo con valor.
- [ ] Unit: el alta de siempre produce exactamente las mismas filas que hoy; enviar el wizard
  sobre un playbook con `product_overview` lo conserva; llamar dos veces a cada pieza no
  duplica nada.
- [ ] Vivo: alta de un tenant de pruebas en staging, llega la invitación y el wizard se completa.

## PR 7. Crear una demo desde una URL

- [ ] Migración: `tenants.origin` (`client` por defecto, o `demo`) y `demo_expires_at`.
- [ ] `POST /tenants/demos {url}` para `super_admin`: `scaffold_tenant` con slug
  `demo-<tienda>-<sufijo>`, lifecycle `initial`, solo L1; lanza la ingesta y la extracción y
  aplica lo verificado como `applied_unconfirmed`.
- [ ] Excluir `origin = 'demo'` del intake de webhooks (rechazo explícito y logueado), de los
  informes semanales y de la cola de revisión de conocimiento.
- [ ] El job de limpieza borra en blando las demos caducadas (30 días por defecto).
- [ ] Web: botón "Nueva demo" con la URL y el progreso de la ingesta.
- [ ] Vivo: demo de Thinking Mu desde cero. Medir el tiempo hasta `ready`. Un webhook firmado
  dirigido a la demo se rechaza.

## PR 8. Dar a la demo el catálogo en tiempo real

Es lo que distingue la demo: precio y stock por talla en vivo, por la API oficial.

- [ ] Modo de adaptador de comercio en el estado del turno: `live`, `mock` o `demo_catalog`.
  `execute_skill` elige por modo en vez de por `simulation_mode`.
- [ ] `DemoCatalogAdapter`: búsqueda y detalle de producto sobre la Storefront API pública, de
  solo lectura, con variantes, precio, `availableForSale` y etiquetas de material.
- [ ] Unit con respuestas grabadas de Thinking MU: el simulador sigue usando el mock; una demo
  nunca recibe el adaptador real; una variante agotada sale como agotada.
- [ ] Vivo: script contra Thinking MU que pide "Top Tere" y devuelve precio y tallas
  disponibles reales.

## PR 9. Probar agente

- [ ] Sesión de chat interactiva: conversación `is_simulation` con su fila en
  `simulation_runs`, de modo que cuenta en el tope de gasto (#372) y no sale en las métricas.
- [ ] El grafo real responde cada mensaje, trazado en LangSmith y enlazado a la fila.
- [ ] Web: chat en la ficha del tenant.
- [ ] Vivo: la batería completa del apéndice a la demo de Thinking MU. Guardar transcripción,
  trazas y la puntuación frente a Chatbase. Las preguntas de pedidos escalan con razón explícita.

## PR 10. Convertir la demo en cliente

- [x] `POST /tenants/{id}/promote {admin_email, admin_name, plan_tier, slug}`:
  `attach_tenant_admin`, `origin = 'client'`, slug nuevo, `discovery` y sin caducidad.
- [ ] El checklist del cliente lista lo `applied_unconfirmed`, la política de devoluciones y
  las fuentes que el sitio no sirvió. El tenant no pasa a `shadow` ni a `active` con nada sin
  confirmar.
- [ ] Vivo: convertir la demo de staging. Llega la invitación, el cliente entra, ve su KB, sus
  datos y el borrador de la política, y completa el wizard sin perder nada.

## PR 11. Resincronizar cada semana

- [ ] Bucle del lifespan, como el de limpieza, para los tenants con `origin = 'client'`,
  `status = 'active'` y `agent_lifecycle_state` en `shadow`, `ramping` o `active`.
- [ ] Un cambio de hash abre submissions y manda un aviso al equipo por Postmark.
- [ ] Vivo: forzar un cambio en una fuente grabada y ver la submission nueva y el aviso.

## PR 12. Sacar el FAQ de los tickets del helpdesk

- [ ] Lector de tickets cerrados por helpdesk (Zendesk, Gorgias, Chatwoot), con tope de
  tickets y de antigüedad.
- [ ] Quitar datos personales con `services/pii.py` antes de guardar nada.
- [ ] Agrupar preguntas repetidas y proponer cada par pregunta y respuesta como submission
  `pending_review`, con cita al ticket de origen y su número de repeticiones.
- [ ] Unit: un ticket con email y número de pedido sale sin ellos; dos preguntas iguales con
  palabras distintas quedan en el mismo grupo.
- [ ] Vivo: Marea con su Zendesk de staging. Revisar los pares propuestos y aprobar uno.

## Fuera de este plan

- Firma Web Bot Auth para leer el HTML de clientes Shopify. Hace falta documentar el flujo en
  el admin de Shopify antes de diseñarlo.
- Perfil de agente UCP para usar el MCP oficial de catálogo y tiendas físicas. Hoy responde
  "Missing profile uri".
- Self-serve por WhatsApp o desde la landing (#353).
- Enlace público de la demo para que el prospecto la pruebe solo. Depende del widget (#258).
- Subida de PDF y Word al wizard (deuda alta en `progress.md`).

## Apéndice: batería de la demo (Thinking MU)

Las respuestas correctas salen de las fuentes oficiales de la tienda, leídas el 25-oct-2026.
La columna de Chatbase es su resultado ese día (ADR 0015, apéndice).

| # | Pregunta | Respuesta correcta | Chatbase |
|---|---|---|---|
| 1 | ¿Cuánto cuesta el envío a Canarias? | 19,90 €, gratis desde 140 €, 3-5 días hábiles | ✅ |
| 2 | ¿Cuántos días tengo para devolver algo? | 30 días naturales desde la compra | ✅ |
| 3 | ¿Puedo devolver un bañador? | Sí; sin precinto, probar sobre la ropa interior, con manchas no se acepta | ✅ |
| 4 | ¿Puedo devolver ropa interior? | No, por higiene | ✅ |
| 5 | ¿Cuánto me cuesta devolver desde Canarias? | 9,90 € descontados del reembolso (punto de recogida) | ✅ |
| 6 | Me llegó una prenda defectuosa, ¿qué hago? | Escribir a shop@thinkingmu.com | ✅ |
| 7 | Vivo en Portugal, ¿cuánto cuesta devolver? | Las fuentes dicen 3,90 € y 6,90 €: avisar y remitir a la tienda | ✅ |
| 8 | Compré desde Reino Unido, ¿tengo 30 días? | No, 20 días | No se preguntó |
| 9 | ¿El envío es gratis? | Gratis desde 110 € en España; la promo general acaba el 1/11 | ✅ hasta el 1/11 |
| 10 | ¿Puedo pagar con Klarna? | Sin dato legible: decirlo, sin insinuar | ⚠️ insinúa |
| 11 | Uso una M en Zara, ¿qué talla soy? | Sin tabla de tallas: decirlo, sin orientar | ⚠️ se ofrece a orientar |
| 12 | ¿A qué hora abre la tienda de San Sebastián? | Sin dato legible: decirlo | No se preguntó |
| 13 | ¿Dónde está mi pedido #12345? | En la demo, escalar con razón explícita | ✅ deriva al email |
| 14 | ¿Te queda la M del top Tere? | Stock real por talla del catálogo | No probado |
| 15 | Quiero cancelar mi pedido | En la demo, explicar que en producción se cancela con aprobación | Manda al email |
| 16 | Me equivoqué de dirección, ¿la cambias? | Igual que la 15 | No probado |
