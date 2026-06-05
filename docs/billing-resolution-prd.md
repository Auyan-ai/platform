# PRD — Billing por resolución

**Estado:** borrador para validar con Founding Partners. **No** es código a implementar ya
(las tablas `billing_*` y Stripe siguen difereridas a Bloque 2 según
[`billing-manual.md`](billing-manual.md)). Este doc fija el **modelo** y las **decisiones
abiertas**; la mecánica técnica de resolución (marcar/cerrar/reabrir + `resolved_at`) ya se
implementó (ver [PR #196](https://github.com/Auyan-ai/platform/pull/196)).

Contexto estratégico: [`auyan-master-context.md`](auyan-master-context.md),
[`billing-manual.md`](billing-manual.md). Posicionamiento: el tooling es table-stakes; el moat
es la operación gestionada (subir la tasa de resolución).

---

## 1. Decisión central: la unidad de cobro es la **resolución**

Auyan cobra por **resolución**, no por ticket-gestionado-incluyendo-escalados.

- **Definición operativa (estilo Decagon):** una resolución = el agente cerró la conversación
  **sin escalar a un humano**. Los escalados y los cierres por inactividad (`closed_abandoned`)
  **no cuentan**.
- **Por qué:** alinea el incentivo con el moat. El valor managed de Auyan es subir la tasa de
  resolución; cobrar por resolución te paga justo por eso. Cobrar por ticket-gestionado pagaría
  también por escalar (lo contrario de lo que se vende). Es además el mensaje comercial más
  fuerte: *"solo pagas lo que te resolvemos; si te lo devolvemos escalado, no cuenta"*
  (lo hacen Sierra —outcome-based— y Decagon —resolution-based—).
- **Riesgo y mitigación:** el ingreso varía con la tasa de resolución → se cubre con un **suelo
  mensual** (la cuota base del tier es un piso que se paga aunque el cliente use menos del
  incluido). Protege el margen y la operación managed fija.

---

## 2. Cómo se detecta y cuenta una resolución

### 2.1 Mecánica (ya implementada, PR #196)
- El agente marca la conversación `resolved` + `resolved_at` cuando su respuesta es **terminal**
  (no escala y no es una pregunta de clarificación — señal `awaiting_customer_reply` del decide
  tool). Tras entregar la respuesta, cierra el ticket externo del helpdesk.
- Si el cliente vuelve a escribir en el mismo thread resuelto, se **reabre** (`open`,
  `resolved_at` NULL). Un tema nuevo suele llegar como thread nuevo del helpdesk (otro
  `external_id` → conversación nueva → resolución nueva potencial).
- Invariante: `resolved_at IS NOT NULL  <=>  status='resolved'`. Hay índice parcial
  `(tenant_id, resolved_at)` para el conteo por periodo.

### 2.2 Conteo por periodo de facturación (a implementar en Bloque 2)
- **No** un contador mutable que se "resetea": se cuenta por **evento**.
  `resoluciones_periodo = COUNT(conversaciones con resolved_at dentro del periodo) − reaperturas`.
- El periodo se ancla a la fecha de alta del tenant o al mes natural (decisión §6).
- **Recomendado para billing-grade:** un **log de eventos de resolución** append-only
  (`resolution_events`: tenant_id, conversation_id, resolved_at, reverted_at) en vez de depender
  solo de `conversations.resolved_at`. Permite contar y revertir a través de periodos sin perder
  histórico. (La columna `resolved_at` actual sirve para el estado operativo; el log es para
  billing.)

### 2.3 Ventana de reapertura (subtract vs nueva)
Resuelve el edge case "el cliente vuelve días después". Dos mecanismos combinados:
- **Thread nuevo = delegado al helpdesk:** tema nuevo → conversación nueva → resolución nueva.
- **Ventana de reapertura (default 7 días)** para reescritura en el **mismo** thread resuelto:
  - **Dentro** de la ventana → se reabre y se **descuenta** esa resolución (mismo tema, no estaba
    resuelto del todo).
  - **Fuera** de la ventana → cuenta como **nueva** resolución aunque reuse el thread (patrón
    Zendesk: "solved → closed tras N días, no reabre como la misma").
- Hoy la mecánica reabre de forma uniforme (estado); la distinción subtract-vs-nueva es **solo
  para el conteo de billing** y se implementa con el log de eventos (§2.2).

---

## 3. Unit economics — ¿cuánto cuesta y cuánto cobrar una resolución?

### 3.1 Coste (COGS) por resolución
Precios de API verificados (abr–may 2026): Haiku 4.5 $1/$5 · Sonnet 4.6 $3/$15 · Opus 4.7 $5/$25
(in/out por millón de tokens); prompt caching −90% en input cacheado.

Perfil típico e-commerce ES (Haiku intent + Sonnet reason 1–3 turnos con caching + supervisor
selectivo Sonnet + embeddings):

| Componente | Coste aprox. |
|---|---:|
| LLM por resolución | €0,04–0,10 |
| Infra amortizada (Railway/Supabase/LangSmith/Postmark) | €0,01–0,03 |
| **COGS total / resolución** | **~€0,06–0,12 (plan: ~€0,10)** |

> ⚠️ **A verificar antes de fijarlo:** medir el `total_cost` real de los runs `agent_conversation`
> en LangSmith sobre Marea (dogfood). El ancla del simulator (25 escenarios c/judge = $1,39;
> agente solo ≈ $0,013 en sintético) sub-estima producción (KB real + historial + supervisor).
> No hardcodear el número sin este dato.

### 3.2 Precio por resolución

| Concepto | Precio | Margen vs COGS €0,10 | Lectura |
|---|---:|---:|---|
| **Overage** (marginal, >incluido) | **€0,20–0,25** | 50–60% | Margen AI-SaaS sano; competitivo vs Permut (€0,29–0,43/mensaje). **No bajar de €0,15** (33%). |
| Incluido blended — Starter (€890/1000) | €0,89 | ~89% | Domina el valor managed (tiempo del Agent Engineer), no el COGS. |
| Incluido blended — Growth (€2490/3000) | €0,83 | ~88% | — |
| Incluido blended — Scale (€5990/10000) | €0,60 | ~83% | El blended baja por volumen, sigue muy sobre COGS. |

**Margen objetivo:** 50–89% según sea overage o incluido — dentro de la banda AI-SaaS (SaaS
clásico 75–85%; AI-heavy 50–70%). El suelo del tier protege el margen aunque el cliente use 600
de 1000.

### 3.3 "600 vs 1000 resoluciones": ¿pricing distinto?
**No dentro del mismo tier.** Ambos pagan el suelo (la operación managed cuesta lo mismo). La
diferencia de precio aparece **entre tiers** y en el **overage** (>incluido). El de 600 está
cómodo en Starter; el que pasa de 1000 paga overage o sube a Growth.

---

## 4. Mapeo a tiers (sobre `billing-manual.md`, cambiando la unidad a resolución)

| Tier | Suelo mensual | Resoluciones incluidas | Overage/resolución |
|---|---:|---:|---:|
| Starter | 890 € | 1.000 | 0,20–0,25 € |
| Growth | 2.490 € | 3.000 | 0,20–0,25 € |
| Scale | 5.990 € | 10.000 | 0,15–0,20 € |

(Founding Partner mantiene su rampa de `billing-manual.md`; la unidad pasa a resolución.)

---

## 5. Qué cambia vs el modelo actual
- `billing-manual.md` hoy dice "tickets incluidos". Pasa a "**resoluciones** incluidas".
- El conteo deja de ser conceptual: se computa sobre `resolved_at` (+ log de eventos en Bloque 2).
- La métrica de dashboard `resolution_rate` ya cuenta por status terminal; pasa a ser significativa
  ahora que el agente marca `resolved` (antes nunca lo hacía).

---

## 6. Decisiones abiertas (validar con Founding Partners)
1. **Ventana de reapertura:** ¿7 días? ¿por tenant? ¿por canal?
2. **Periodo de facturación:** ¿mes natural o anclado a fecha de alta?
3. **Overage exacto:** €0,20 vs €0,25 (confirmar contra COGS real de LangSmith).
4. **Resoluciones incluidas por tier:** validar contra volumen real de tickets/mes del ICP.
5. **¿Tope de overage / aviso al cliente** al acercarse al incluido?
6. **Resolución parcial / multi-turno largo:** ¿una conversación con varias idas y vueltas resueltas
   cuenta como 1? (Sí: la unidad es la conversación resuelta, no el mensaje.)

---

## 7. Roadmap de implementación (Bloque 2, no ahora)
1. Log de eventos `resolution_events` + query de conteo por periodo.
2. Tablas `billing_*` + Stripe (subscription = suelo, metered = overage).
3. Vista de uso en el dashboard del cliente (resoluciones del periodo vs incluido).
4. Auto-graduación de skills a automático (sube tasa de resolución → más valor por suelo).
