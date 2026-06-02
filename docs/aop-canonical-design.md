# AOPs canónicos de Auyan — diseño + sesión de comprensión

> Doc vivo. Objetivo de la sesión: definir los **AOPs por defecto de Auyan e-commerce ES**
> (los que hereda CADA tenant nuevo; luego se personalizan por vertical/cliente) y dejar
> el grafo + los AOPs en 10/10. Esto desbloquea el dogfood E2E con Marea.

## Modelo: Opus (diseño estructural del grafo + AOPs). Confirmado.

---

## Checklist de comprensión (Kenny)

### 1. El problema
- [x] Por qué "AOPs canónicos" ≠ "los 3 AOPs de prueba de un tenant" (defaults de plataforma vs seed manual)
- [x] Por qué el fallback `default` NO puede tener skills destructivas (principio de seguridad) — *confirmado vía quiz*
- [x] Qué significa "config muerta" y por qué `confidence_threshold`/`require_supervision` por-AOP hoy no hacen nada — *confirmado vía quiz*
- [x] Las DOS confidences distintas: intent (selección de AOP) vs respuesta (escalado)
- [x] Por qué el grafo reclasifica **ciego** cada turno (state no persiste, sin checkpointer) → riesgo de **flapping**, no stickiness — *corregido tras verificar*

### 2. La solución
- [x] El set canónico de AOPs (cuáles, granularidad, por qué) — 8 procedimentales
- [x] Postura de write-actions en los defaults (L1/L2 auto, L3 approval; super_admin gradúa)
- [x] Wiring de los campos por-AOP (threshold, supervision) + intent-switch — *#164 (threshold/supervision) + Fix #5 (intent-switch continuity-aware), sesión 60*
- [ ] Cómo se provisiona el set a un tenant nuevo (no script manual)

### 3. El contexto amplio
- [ ] Por qué estos defaults son la "clase base" y cómo el override por-tenant no debe romperlos
- [ ] Qué impacta en Marea (dogfood E2E) y en la venta

---

## Verificación del informe del agente paralelo (grounded contra el código)

Veredicto: **el informe está calibrado para un greenfield MVP. Auyan está muy por delante
de eso.** La mayoría de sus "obligatorios" YA están implementados; un consejo suyo
("no construyas writes todavía") sería una **regresión**; y acierta en ~5 gaps reales.

### A. Ya implementado (el informe va por detrás)
| Informe dice "sí o sí" | Realidad en el código |
|---|---|
| 5.1 Multi-tenant seguro | RLS en aops/aop_versions/intent_runs + `tenant_scope` en cada query. ✅ |
| 5.3 Fallback unknown_intent | `default` + `intent_min_confidence` en `select_aop`. ✅ (refinable) |
| 5.4 Estado estructurado | `AgentState` rico (sin `collected_fields`; replay de historial+tool_results). ✅ |
| 5.5 Continuar AOP activo | `aop_locked_until_turn` + `_should_reclassify`. ✅ |
| 5.6 RAG filtrado por tenant | `search_knowledge_chunks(tenant_id)`. ✅ |
| 5.7 No inventar | Reglas globales anti-alucinación + bloque KB en el compiler. ✅ |
| 5.9 Tools tenant∩aop∩runtime | 3 capas: `tenant_tool_permissions` ∩ `allowed_skills` ∩ tier→approval/supervisor. ✅ **excede** |
| 5.11 Logs | reasoning events + `intent_classifier_runs` + skill_audit + costo + LangSmith. ✅ **excede** |
| 6.6 Versionado de AOPs | `aop_versions` append-only (trigger inmutable). ✅ **excede** |

### B. Donde el informe está EQUIVOCADO para Auyan
- **Triggers por keywords + `negative_triggers`**: Auyan clasifica **semánticamente con Haiku**
  (catálogo name+description). El keyword-matching del informe es un downgrade. Se rescata el
  *espíritu* (ejemplos few-shot, qué NO pertenece) metiéndolo en la description.
- **"No construyas refunds/cancelaciones/cambios de dirección todavía"**: Auyan **ya tiene** 11
  skills Shopify (L1/L2/L3) con approval + supervisor. Seguir esto sería arrancar capability.
- **"Te paso con un humano" / agentes humanos**: Auyan NO es BPO. Escalar = push al equipo CX
  **del cliente**. Framing del informe asume humanos propios.
- **RAG como palanca principal de calidad**: para CX e-commerce, la calidad la mueve más la
  **calidad del procedimiento (AOP) + ejecución de skills** (lookups, returns). RAG es secundario.

### C. Donde ACIERTA — gaps reales para el 10/10
1. **Fallback seguro** (5.3+5.9): el `default` actual trae `cancel_order` (L3) y
   `update_shipping_address` (L2). Baja confianza → desbloquea destructivas. ⚠️ **el más importante.**
2. **Guard anti prompt-injection** en contenido recuperado (5.8): el bloque KB tiene
   anti-alucinación pero no "esto son datos, no instrucciones". Fix barato.
3. **Query-rewrite con contexto del AOP** (6.2): RAG multi-turn pierde contexto ("¿y si ya lo abrí?").
4. **Categorías de KB por AOP** (6.5): que returns no recupere chunks de envíos.
5. **Per-AOP test scenarios** (5.13): infra existe (evals + simulator); falta el set canónico
   con la matriz ambiguo / falta-dato / tool-falla.

### Gaps de wiring encontrados en el código (no estaban en el informe)
- `confidence_threshold` por-AOP **no se propaga** desde `select_aop` → `reason` usa el global.
- `require_supervision` por-AOP **no se propaga** → `needs_supervision` mira `tenant_config.extra`.
- `pending_intent` (desambiguación) **se escribe y nunca se lee**.

> Para 10/10: o cableamos estos 3 campos (rigurosidad por-procedimiento real) o los quitamos
> del contrato. La recomendación es **cablearlos** — son justo lo que distingue un AOP "serio".

---

## Decisiones tomadas (sesión)

- **Modelo:** Opus. **Granularidad:** procedimental, 8 AOPs.
- **Postura canónica de autonomía:** L1/L2 autónomos; los 4 L3 nacen `enabled` + `human_approval_required=true`. Kenny (super_admin/managed) gradúa por cliente con la política de abajo. `default` SIN writes.
- **returns y refunds SEPARADOS.** Depende de arreglar intent-switch (ver abajo).
- **complaint:** acusa recibo (empatía + "lo escalo a una persona") + tag_order + escala con resumen. Sin L3.
- **Approval L3 se da en el dashboard de Auyan** (`/clients/[tenantId]/approvals` y `/(dashboard)/tenants/[tenantId]/approvals`), NO en el helpdesk. El approve ejecuta la skill server-side y postea `agent_human`. El helpdesk solo transporta mensajes al cliente final.

### Skills reales (verificado)
- **L1:** get_order_status, get_order_by_email, get_product_info, get_shop_policies, get_customer_history
- **L2:** add_order_note, tag_order
- **L3:** cancel_order, refund_partial, start_return, **update_shipping_address** (¡es L3, no L2!)

### Política de graduación L3 → automático (propuesta; candidata a ADR)
Lever técnico: `tenant_tool_permissions.human_approval_required=false` (lo pone super_admin). Cuándo:
| Gate | Criterio |
|---|---|
| Volumen | ≥ 30 ejecuciones L3 reales de ese (tenant, skill) en modo approval |
| Calidad | ≥ 95% aprobadas + 0 incidentes post-aprobación, ventana móvil |
| Tiempo | sostenido ≥ 2–4 semanas |
| Consentimiento | Auyan muestra el dato → cliente dice "sí" |
| Techo en auto | refund con cap de importe (`threshold_override`) + supervisor Opus sigue activo |
| Auto-demote | si sube error/queja en auto → vuelve a approval-required |

---

## Principio: los canónicos son TENANT-AGNÓSTICOS
Cero constantes de tenant en frontmatter/body. NADA de "30 días" ni "EUR" hardcodeados
(el `returns` actual los hardcodea → bug como default). Referenciar dinámicamente:
`tenant_facts.return_window_days`, `get_shop_policies` (skill), la moneda del pedido.
El mecanismo ya existe (bloque de facts del compiler + `_FACTS_LABEL_MAP`). Esto ES la
"clase base": cada tenant la hereda igual y la personaliza vía facts/playbook/overrides,
sin tocar el AOP canónico.

## Set canónico (8 AOPs) — e-commerce ES

| AOP | Trigger (description) | allowed_skills (tier) | thr. | superv. | escalación |
|---|---|---|---|---|---|
| `order_status` | estado/tracking/entrega de un pedido hecho | get_order_status, get_order_by_email `L1` | 0.65 | no | dañado / entregado-no-recibido |
| `shipping_info` | tiempos/costes/zonas de envío (general) | get_shop_policies `L1` | 0.60 | no | fuera de cobertura |
| `returns` | devolver / iniciar devolución (mercancía) | get_order_status, get_order_by_email, get_shop_policies, start_return `L3` | 0.70 | resp. | fuera de plazo / agresivo / digital |
| `refunds` | dinero de vuelta / estado de reembolso | get_order_status, get_shop_policies, refund_partial `L3` | 0.78 | sí | importe alto / disputa |
| `product_info` | disponibilidad/specs/tallas/stock | get_product_info, get_shop_policies `L1` | 0.60 | no | producto inexistente |
| `order_change` | cambiar dirección / cancelar pedido | get_order_status, update_shipping_address `L3`, cancel_order `L3` | 0.72 | resp. | ya enviado / pago en disputa |
| `complaint` | dañado, no recibido, enojado, amenaza legal | get_order_status, get_customer_history `L1`, tag_order, add_order_note `L2` | 0.70 | sí | escalate-first salvo trivial |
| `default` | catch-all / baja confianza | get_shop_policies, get_product_info, get_order_status, get_customer_history `L1` | 0.60 | no | sin info confiable → escala |

`thr.` = `confidence_threshold` por-AOP (requiere wiring). `superv.=resp.` = supervisor revisa la respuesta (los L3 ya disparan supervisor por tier).

---

## HALLAZGO CRÍTICO (corregido) — reclasificación CIEGA cada turno

**Verificado:** el grafo NO usa checkpointer (`graph.compile()` sin args; `ainvoke(initial_state)`
sin config/thread_id) y `process_inbound` arma el `initial_state` desde cero en cada mensaje,
SIN `aop_slug` (service.py:71-88). Nadie seedea el AOP previo entre turnos.

→ El state **no persiste entre turnos**. `aop_slug` nace vacío cada turno →
`_should_reclassify` cae en `if not state.get("aop_slug"): return True` → **el clasificador corre
SIEMPRE.** NO es sticky: el intent-switch ya ocurre cada turno.

Consecuencias:
- `aop_locked_until_turn`/`aop_completed_signal`/`pending_intent` = scaffolding inerte (solo
  tendrían sentido entre turnos —no hay persistencia— o más adelante en el mismo invoke —nadie los lee).
- **La conversación NO se pierde al cambiar de AOP**: `load_conversation` recarga el historial
  (ventana `history_limit`, default 20) desde DB cada turno, independiente del AOP. El AOP solo
  cambia el *system_prompt*, no los *mensajes*. reason re-reproduce todo.
- Riesgo real con 8 AOPs: **flapping mid-procedimiento** en respuestas cortas/ambiguas ("el azul",
  "12345") → la reclasificación ciega salta de AOP y pierde el hilo. NO quedarse atascado.

**Fix (Approach 1, re-justificado): reclasificación continuity-aware.**
1. `select_aop` CARGA el AOP previo desde DB (última fila de `intent_classifier_runs` de la
   conversación — sin migración nueva).
2. Lo pasa al prompt del clasificador → "venías en `returns`; ¿continúa o cambió?".
3. Histéresis: cambia de AOP solo si el nuevo intent ≥ `switch_threshold` (~0.70).
4. Sigue corriendo cada turno (ya lo hace), pero **informado** (no ciego).
5. Retira el scaffolding de locks; `pending_intent` → multi-intent en 1 mensaje (opcional).

---

## Fixes de grafo para 10/10 (consolidado)
1. **Intent-switch continuity-aware** (el grande): el grafo YA reclasifica cada turno pero CIEGO.
   Cargar AOP previo desde `intent_classifier_runs` + pasarlo al clasificador + histéresis. Anti-flapping.
   **+ Desambiguación por pregunta:** si `ambiguity_detected` y |conf(primary) − conf(alternative)| ≤ 0.15,
   inyectar en el system_prompt una guía para que el agente haga UNA pregunta de aclaración (ej: "¿es sobre un
   pedido que ya hiciste o información general?") antes de actuar; el siguiente turno reclasifica limpio.
   Da uso por fin a `ambiguity_detected`/`pending_intent` (hoy muertos).
2. **Wire `confidence_threshold` por-AOP** (select_aop → state → reason; hoy usa el global).
3. **Wire `require_supervision` por-AOP** (select_aop → state → needs_supervision; hoy mira tenant_config.extra).
4. **Guard anti prompt-injection** en bloque KB + tool_results del compiler ("datos, no instrucciones").
   Vive en el compiler (frontera de confianza) → ningún tenant lo borra editando su AOP. DRY + invariante de seguridad.
5. **Fecha/hora TZ-aware + plazos deterministas** (correctitud de returns/refunds). Hoy: `datetime.now(UTC).date()`
   (UTC, sin hora) y el LLM resta fechas → off-by-one en frontera para tiendas ES. Fix: `timezone` de tenant
   (default `Europe/Madrid`) + inyectar datetime local con hora + calcular `days_since_order` en código
   (TZ-aware, desde `created_at` de Shopify) y exponerlo en el output del pedido. El LLM compara números, no fechas.
6. *(Fase 2)* RAG: query-rewrite con contexto del AOP + categorías de KB por AOP.

## Provisioning (pendiente de decidir)
Hoy los AOPs se siembran por-tenant a mano (`seed_test_aops.py`). Los canónicos deben
auto-provisionarse al crear el tenant (o un `seed_canonical_aops.py` + hook de onboarding).

---

## DRAFT — patrón a aprobar: `order_status`

> Convenciones del patrón (aplican a los 8):
> - **Anti-injection** NO va en el body: vive en el compiler (fix #4), envolviendo KB + tool_results + texto del cliente. DRY.
> - **Tenant-agnóstico**: cero constantes. Plazos/moneda/tiempos salen de `tenant_facts`, `get_shop_policies` o del pedido.
> - **Body = procedimiento**: pasos imperativos, decision points explícitos, sin gritar en MAYÚS, sin repetir.
> - **`triggers.examples`**: few-shot para el clasificador (rescata el espíritu de "triggers/negative" del informe; requiere que select_aop los meta al catálogo — fold en fix #1).
> - `confidence_threshold`/`require_supervision` dependen de fixes #2/#3 para tener efecto.

### Frontmatter
```yaml
name: "Estado de pedido"
slug: order_status
workspace: production
triggers:
  description: >
    El cliente pregunta por el estado, ubicación, tracking o fecha de entrega de un
    pedido que YA realizó. NO es: iniciar devolución (returns), cancelar/cambiar
    dirección (order_change), ni dudas de envío pre-compra (shipping_info).
  examples:
    - "¿dónde está mi pedido?"
    - "no me ha llegado lo que compré"
    - "¿me das el tracking del #1234?"
    - "¿cuándo llega mi compra?"
allowed_skills:
  - shopify.get_order_status      # L1
  - shopify.get_order_by_email    # L1
required_data:
  - "Identificador del pedido: nº de pedido O el email de la compra"
guardrails:
  - "Nunca inventes tracking, transportista ni fecha de entrega: solo lo que devuelva la skill."
  - "Pedido 'unfulfilled' (en preparación, sin tracking) es normal; NO escales por eso."
  - "La impaciencia no es motivo de escalado: recalcula días desde created_at y tranquiliza con el dato real."
max_tool_iterations: 4
confidence_threshold: 0.65
require_supervision: false
escalation_triggers:
  - "El cliente reporta el pedido dañado o incompleto"
  - "El pedido figura entregado pero el cliente dice no haberlo recibido"
```

### Body
```markdown
## Procedimiento: estado de pedido
Objetivo: decirle al cliente dónde está su pedido con datos reales, sin inventar.

1. Si dio nº de pedido (#1234) → `shopify.get_order_status`. Si dio solo email → `shopify.get_order_by_email`.
2. Si no dio ninguno → pídele el nº de pedido o el email de la compra antes de consultar.
3. Si el email tiene varios pedidos → pregúntale cuál (menciónalos por fecha y nº).
4. Con el pedido:
   - Con tracking → comparte estado + transportista + nº de tracking + link de seguimiento.
   - Sin tracking (en preparación) → dilo como algo normal; si se queja del retraso, calcula los días
     desde `created_at` y tranquilízalo con ese dato concreto.
5. Cierra preguntando si necesita algo más.
```

### Eval harness (3 capas)
**(a) Compilación** (fixtures YAML, estilo actual): `compile_ok`, `slug_in_frontmatter`,
`allowed_skills` solo L1, `no_l3_skills`, `confidence_threshold_between [0.6,0.7]`,
`has_escalation_triggers`, `tool_defs_match_skills`.

**(b) Clasificación de intent** (nueva capa — message → primary_slug esperado):
- Debe activar (5): "¿dónde está mi pedido?", "no me ha llegado", "tracking del #1234", "¿cuándo llega?", "mi paquete no aparece"
- NO debe activar (3): "quiero devolver" (→returns), "cuánto tardan los envíos" (→shipping_info), "cancela mi pedido" (→order_change)
- Ambiguo (2): "mi pedido tiene un problema" (¿complaint?), "12345" suelto (continuación → depende del AOP previo)

**(c) Comportamiento E2E** (simulator, fixtures Shopify mock):
- falta identificador → lo pide, no consulta
- pedido fulfilled → comparte tracking
- pedido unfulfilled + cliente impaciente → tranquiliza con días, NO escala
- pedido no encontrado → pide más datos / escala
- skill falla (500) → trata como dato no disponible, escala, no inventa

---

## DRAFT — `returns` (segundo patrón, L3)
```yaml
name: "Devoluciones"
slug: returns
workspace: production
triggers:
  description: >
    El cliente quiere devolver un producto / iniciar una devolución (la MERCANCÍA de
    vuelta). Si pide SOLO el dinero sin devolver producto → refunds. Cancelar un pedido
    no enviado → order_change. Producto dañado/no recibido → complaint.
  examples:
    - "quiero devolver esta camiseta"
    - "¿cómo inicio una devolución?"
    - "el producto no me sirve, lo quiero devolver"
allowed_skills:
  - shopify.get_order_status     # L1
  - shopify.get_order_by_email   # L1
  - shopify.get_shop_policies    # L1 — fuente de verdad del plazo
  - shopify.start_return         # L3 — gated por approval (default)
required_data:
  - "Identificador del pedido (nº o email)"
  - "Qué artículo(s) quiere devolver y el motivo"
guardrails:
  - "Confirma elegibilidad con la política REAL (get_shop_policies / tenant_facts), nunca con un plazo asumido."
  - "Fuera del plazo de la tienda → no inicies la devolución: explícalo con empatía y escala si insiste."
  - "Productos excluidos por la política (digitales/perecederos) no admiten devolución."
  - "No inicies start_return hasta tener artículo y motivo confirmados."
max_tool_iterations: 5
confidence_threshold: 0.70
require_supervision: true
escalation_triggers:
  - "El pedido está fuera del plazo de devolución de la tienda"
  - "El cliente es agresivo o amenazante"
  - "La política excluye el producto y el cliente insiste"
```
**Body:**
```markdown
## Procedimiento: devolución
Objetivo: ayudar a devolver un producto elegible, según la política real de la tienda.
1. Identifica el pedido: nº → get_order_status; email → get_order_by_email.
2. Consulta get_shop_policies (plazo, condiciones, exclusiones). Es la fuente de verdad — no asumas plazos.
3. Elegibilidad: compara created_at con el plazo usando la fecha actual (TZ de la tienda, fix #5).
   - Elegible → continúa.  - Fuera de plazo / excluido → explícalo con empatía, no inicies, escala si insiste.
4. Confirma con el cliente QUÉ artículo(s) y el MOTIVO.
5. start_return mapeando desde el pedido (order_id, line_item_id, quantity, reason). Queda en aprobación.
   Explica el siguiente paso: enviar el producto, y que el reembolso se emite cuando se reciba y verifique.
6. Si solo quiere el dinero (sin devolver) o pregunta por un reembolso → es refunds; el grafo reclasifica.
7. Tono profesional siempre.
```
**Eval:** activa: "quiero devolver", "¿cómo hago una devolución?", "el producto no me sirve", "devolver el pedido #123" · no-activa: "¿dónde está mi pedido?" (order_status), "llegó roto" (complaint), "me cobraron de más" (refunds) · E2E: dentro de plazo→start_return pendiente + explica envío y reembolso-tras-recepción; fuera de plazo→no inicia, empatía+escala; excluido→no inicia; pide solo dinero→reconduce a refunds.

---

## DRAFTS — los 6 restantes

### `shipping_info`
```yaml
name: "Información de envío"
slug: shipping_info
workspace: production
triggers:
  description: >
    Dudas GENERALES de envío: plazos, costes, zonas/países, métodos, envío gratis.
    Normalmente pre-compra o de política. NO es el estado de un pedido concreto ya
    hecho (eso es order_status), ni devoluciones.
  examples:
    - "¿cuánto tarda en llegar un pedido?"
    - "¿hacéis envíos a Canarias / Baleares?"
    - "¿el envío es gratis a partir de cuánto?"
allowed_skills:
  - shopify.get_shop_policies     # L1
required_data: []
guardrails:
  - "No inventes plazos, costes ni zonas: usa get_shop_policies o la KB. Si no está, dilo y escala."
  - "No confundas tiempo de envío (en tránsito) con tiempo de preparación."
max_tool_iterations: 3
confidence_threshold: 0.60
require_supervision: false
escalation_triggers:
  - "Destino/país fuera de la cobertura conocida de la tienda"
  - "Dudas de aduanas/impuestos de importación que la política no cubre"
```
**Body:**
```markdown
## Procedimiento: información de envío
Objetivo: responder dudas generales de envío con la política real de la tienda y la KB.
1. Apóyate en DOS fuentes: el contexto de la KB inyectado (si lo hay) y `get_shop_policies`.
   Si falta el dato en ambas, no inventes: dilo y escala.
2. Si preguntan por un destino concreto → confirma cobertura; si no está, dilo y escala.
3. Distingue preparación vs tránsito al dar plazos.
4. Si en realidad preguntan por SU pedido concreto → es order_status; el grafo reclasifica.
```
**Eval:** activa: "¿cuánto tarda el envío?", "¿enviáis a Baleares?", "¿envío gratis?", "¿qué mensajería usáis?", "¿puedo elegir envío urgente?" · no-activa: "¿dónde está mi pedido?" (order_status), "quiero devolver" (returns) · E2E: política con datos→responde; destino no cubierto→escala; sin dato en política→no inventa, escala.

---

### `refunds`
```yaml
name: "Reembolsos"
slug: refunds
workspace: production
triggers:
  description: >
    El cliente pregunta por el ESTADO de un reembolso en curso, o pide dinero de vuelta
    por un cobro incorrecto / ajuste de precio NO ligado a devolver mercancía. Devolver
    producto físico → returns (el reembolso va tras recibir el artículo). Dañado/no
    recibido → complaint. Cancelar pedido no enviado → order_change.
  examples:
    - "quiero que me devuelvan el dinero"
    - "¿cuándo me llega el reembolso?"
    - "me han cobrado dos veces"
allowed_skills:
  - shopify.get_order_status      # L1
  - shopify.get_order_by_email    # L1
  - shopify.get_shop_policies     # L1
  - shopify.refund_partial        # L3 — gated por approval (default), cap de importe
required_data:
  - "Identificador del pedido (nº o email)"
  - "Motivo del reembolso y artículo/importe afectado"
guardrails:
  - "El reembolso por una DEVOLUCIÓN se emite tras recibir y verificar el producto: eso es returns, no aquí. No prometas reembolso inmediato por devolver algo."
  - "refund_partial solo para casos DIRECTOS sin devolución (sobrecobro, ajuste de precio acordado). Importe y moneda salen del pedido, nunca inventados."
  - "El reembolso queda pendiente de aprobación; no afirmes que ya se hizo."
  - "Daño/no-recibido/disputa/importe alto/reembolso total → escala, no lo fuerces."
  - "Comprueba que no exista ya un reembolso para ese pedido antes de iniciar otro."
max_tool_iterations: 5
confidence_threshold: 0.78
require_supervision: true
escalation_triggers:
  - "Importe alto o reembolso total"
  - "Disputa, chargeback o sospecha de fraude"
  - "El cliente alega cobro duplicado"
```
**Body:**
```markdown
## Procedimiento: reembolso
Objetivo: estado de reembolsos + reembolsos DIRECTOS sin devolución; el resto, escalar o reconducir.
1. ¿Pregunta por el ESTADO de un reembolso? → get_order_status (revisa los refunds del pedido) e informa.
2. ¿Sobrecobro o ajuste de precio claro y dentro de política (SIN devolver producto)? → refund_partial
   (order_id, amount, currency del pedido). Queda en aprobación; informa.
3. ¿Quiere el dinero por DEVOLVER un producto? → es returns: el reembolso se emite tras recibir y verificar
   el artículo. Reconduce (el grafo reclasifica).
4. Daño/no-recibido → complaint. Disputa, importe alto o reembolso total → escala con resumen.
```
**Eval:** activa: "¿dónde está mi reembolso?", "me cobraron de más", "el cargo es incorrecto", "no me aplicaron el descuento" · no-activa: "quiero devolver la camiseta" (returns), "llegó roto, devuélveme el dinero" (complaint), "cancela el pedido" (order_change) · E2E: estado→informa; sobrecobro dentro de política→refund_partial pendiente (moneda del pedido); devolución→reconduce a returns (no reembolsa); daño→complaint; importe alto→escala.

---

### `product_info`
```yaml
name: "Información de producto"
slug: product_info
workspace: production
triggers:
  description: >
    Dudas pre-compra sobre un producto: disponibilidad/stock, tallas, materiales,
    specs, precio. NO es estado de pedido ni devolución.
  examples:
    - "¿tenéis esta camiseta en talla M?"
    - "¿de qué material está hecho?"
    - "¿cuándo reponéis stock?"
allowed_skills:
  - shopify.get_product_info      # L1
  - shopify.get_shop_policies     # L1
required_data:
  - "Qué producto: nombre, variante o SKU"
guardrails:
  - "No inventes specs, stock ni precios: usa get_product_info. El stock refleja lo que devuelve la skill."
  - "Si no identificas el producto, pide nombre/variante antes de responder."
max_tool_iterations: 3
confidence_threshold: 0.60
require_supervision: false
escalation_triggers:
  - "El producto no existe en el catálogo"
  - "Pregunta técnica que la ficha no cubre"
```
**Body:**
```markdown
## Procedimiento: información de producto
Objetivo: responder dudas de producto con la ficha real, sin inventar.
1. Identifica el producto (nombre/variante/SKU). Si es ambiguo, pídelo.
2. get_product_info para disponibilidad, specs, precio.
3. Responde solo con lo que devuelve la skill; el stock puede cambiar.
4. Garantía/condiciones → get_shop_policies.
5. Si no existe o la ficha no cubre la duda → dilo y escala.
```
**Eval:** activa: "¿hay stock de X?", "¿talla M disponible?", "¿de qué material?", "¿cuánto cuesta el modelo Y?", "¿cuándo repones?" · no-activa: "¿dónde está mi pedido?" (order_status) · E2E: producto encontrado→specs reales; ambiguo→pide variante; inexistente→escala; no inventa stock.

---

### `order_change`
```yaml
name: "Cambio o cancelación de pedido"
slug: order_change
workspace: production
triggers:
  description: >
    El cliente quiere MODIFICAR un pedido ya hecho que aún no se ha enviado: cambiar
    la dirección de envío o cancelarlo. NO es devolver (returns) ni reembolso de algo
    ya entregado (refunds).
  examples:
    - "quiero cambiar la dirección de envío"
    - "cancela mi pedido por favor"
    - "puse mal el código postal"
allowed_skills:
  - shopify.get_order_status        # L1
  - shopify.update_shipping_address # L3 — gated por approval (default)
  - shopify.cancel_order            # L3 — gated por approval (default)
required_data:
  - "Identificador del pedido"
  - "Para dirección: todos los campos nuevos (address1, city, province, country, zip)"
guardrails:
  - "Solo cambias dirección o cancelas si el pedido NO se ha enviado (unfulfilled). Si ya se envió → no es posible; explícalo y ofrece la vía de devolución / escala."
  - "Para cambio de dirección, recoge TODOS los campos nuevos antes de llamar la skill."
  - "Cambio y cancelación quedan pendientes de aprobación; informa que está en proceso."
  - "No canceles ni modifiques sin petición explícita del cliente."
max_tool_iterations: 5
confidence_threshold: 0.72
require_supervision: true
escalation_triggers:
  - "El pedido ya fue enviado/fulfilled"
  - "Pago en disputa"
  - "El cliente pide modificar artículos o cantidades (no soportado)"
```
**Body:**
```markdown
## Procedimiento: cambio o cancelación de pedido
Objetivo: modificar (dirección) o cancelar un pedido AÚN NO enviado, con aprobación.
1. Localiza el pedido (get_order_status) y comprueba el estado de fulfillment.
2. Si ya está enviado (fulfilled) → no se puede cambiar/cancelar; explícalo y reconduce a devolución o escala.
3. Cambio de dirección (unfulfilled): recoge TODOS los campos nuevos → update_shipping_address (order_id + dirección). Pendiente de aprobación; informa.
4. Cancelación (unfulfilled): confirma la intención → cancel_order (order_id). Pendiente de aprobación; informa.
5. Modificar artículos/cantidades no está soportado → escala.
```
**Eval:** activa: "cambia la dirección", "cancela mi pedido", "me equivoqué de dirección", "anula el pedido", "quita un artículo" (→ escala) · no-activa: "quiero devolver" (returns), "¿dónde está mi pedido?" (order_status) · E2E: unfulfilled+dirección completa→update pendiente; unfulfilled+cancela→cancel pendiente; ya enviado→no posible, reconduce; faltan campos→los pide.

---

### `complaint`
```yaml
name: "Queja / incidencia"
slug: complaint
workspace: production
triggers:
  description: >
    Incidencia o queja seria: producto dañado/defectuoso, pedido no recibido pese a
    figurar entregado, cliente muy enfadado o amenaza legal. Prioridad: acusar recibo
    con empatía y escalar a una persona.
  examples:
    - "el producto llegó roto"
    - "pone entregado pero no he recibido nada"
    - "esto es inaceptable, voy a reclamar"
allowed_skills:
  - shopify.get_order_status      # L1
  - shopify.get_customer_history  # L1
  - shopify.tag_order             # L2
  - shopify.add_order_note        # L2
required_data: []
guardrails:
  - "No prometas compensación, reembolso ni reenvío: eso lo decide el equipo humano."
  - "Mantén tono empático y calmado, incluso ante agresividad o amenazas."
  - "No admitas culpa legal ni hagas declaraciones que comprometan a la empresa."
  - "Recoge contexto y escala con un resumen claro; no intentes resolver tú la incidencia."
max_tool_iterations: 4
confidence_threshold: 0.70
require_supervision: true
escalation_triggers:
  - "Toda queja seria (dañado, no recibido, amenaza legal) → escala tras acusar recibo"
```
**Body:**
```markdown
## Procedimiento: queja / incidencia
Objetivo: contener con empatía y escalar a una persona con contexto. NO resolver tú.
1. Reconoce el problema con empatía, sin prometer soluciones concretas.
2. Recoge contexto: get_order_status (si hay pedido) y get_customer_history.
3. Marca el pedido como incidencia con tag_order y deja un add_order_note con el resumen para el equipo.
4. Dile al cliente que lo estás escalando a una persona que lo revisará en breve.
5. Escala con resumen: pedido, naturaleza de la incidencia y contexto relevante.
```
**Eval:** activa: "llegó roto", "no recibí pero pone entregado", "voy a denunciar", "llevo días sin respuesta y estoy harto", "producto defectuoso" · no-activa: "¿dónde está mi pedido?" (order_status, sin incidencia), "quiero devolver" (returns) · E2E: acusa recibo+tag+escala con resumen; no promete compensación; tono calmado ante agresividad; supervisor revisa la respuesta.

---

### `default` (fallback SEGURO)
```yaml
name: "Atención general"
slug: default
workspace: production
triggers:
  description: >
    Catch-all para mensajes que no encajan claramente en otro procedimiento o cuando
    la confianza del clasificador es baja. Solo lectura: informar y, si hace falta una
    acción, escalar.
  examples:
    - "hola, tengo una duda"
    - "¿me podéis ayudar?"
allowed_skills:
  - shopify.get_shop_policies     # L1
  - shopify.get_product_info      # L1
  - shopify.get_order_status      # L1
  - shopify.get_customer_history  # L1
required_data: []
guardrails:
  - "No inventes: si no está en la KB, las políticas o el output de una skill, dilo y escala."
  - "No tienes herramientas de escritura. Si el cliente pide una acción (cancelar, reembolsar, cambiar, devolver), recoge contexto y escala — o el grafo reclasificará al AOP adecuado."
max_tool_iterations: 4
confidence_threshold: 0.60
require_supervision: false
escalation_triggers:
  - "No hay información confiable para responder"
  - "El cliente pide una acción que requiere herramientas no disponibles aquí"
```
**Body:**
```markdown
## Procedimiento: atención general
Objetivo: ayudar con información de solo lectura; ante acciones, escalar.
1. Entiende qué necesita. Si es info (envíos, garantías, producto, estado de pedido) → usa la skill L1 que corresponda.
2. Responde solo con datos reales (skill/KB). Si no los tienes → dilo y escala.
3. No tienes herramientas de escritura: si pide una acción, recoge el contexto y escala (o el grafo reclasifica).
4. Sé honesto sobre lo que sabes y lo que no.
```
**Eval:** activa: saludos/dudas vagas, mensajes mixtos de baja confianza, "¿me ayudas con una cosa?" · no-activa: cualquier intent claro (debe ganar su AOP específico) · E2E: NUNCA tiene L2/L3 (test de seguridad: `no_write_skills`); info L1→responde; pide acción→escala; sin dato→no inventa.

---

## Roadmap — integración de devoluciones (Reveni / Shopify Returns / Loop)
Muchas tiendas ES usan plataformas de devoluciones-as-a-service (ej. **Reveni**) que gestionan portal,
etiqueta, recepción y el reembolso correcto. Modelo objetivo: si el tenant usa una de estas, `returns`
**delega** en la plataforma en vez de llamar a `shopify.start_return`/`refund_partial` directo.

- **Forward-compatible**: el AOP `returns` no cambia de forma; solo se sustituye la skill
  (`shopify.start_return` → `reveni.create_return`) y la plataforma maneja el reembolso post-recepción.
- **A investigar** (antes de cablear): API de Reveni, modelo de auth, webhooks de estado de devolución,
  cómo expone el reembolso. NO asumir nada hasta verificar.
- Fuera del scope de los AOPs canónicos actuales (que trabajan con las skills Shopify que ya existen),
  pero el diseño ya lo contempla.
