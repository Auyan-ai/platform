# Motor de billing por resolución

Qué mide el código de billing y cómo. El cobro real (Stripe) **no existe todavía**: el motor
mide consumo y calcula el importe del periodo, no cobra.

Código: `apps/api/services/billing.py`, modelos en `apps/api/db/models.py` (sección Billing),
migración `supabase/migrations/20260621000001_add_billing_resolution_events.sql`.

---

## 1. Unidad de cobro: la resolución

Una **resolución** = el agente cerró la conversación **sin escalar a un humano**. Los escalados
y los cierres por inactividad (`closed_abandoned`) **no cuentan**. La unidad es la conversación
resuelta, no el mensaje: una conversación con varias idas y vueltas cuenta como 1.

Cada suscripción tiene un **suelo mensual** (se paga aunque se use menos de lo incluido) +
**overage** por resolución por encima de lo incluido.

---

## 2. Cómo se detecta y cuenta una resolución

### 2.1 Mecánica de estado (PR #196)
- El agente marca la conversación `resolved` + `resolved_at` cuando su respuesta es **terminal**
  (no escala y no es una pregunta de clarificación — señal `awaiting_customer_reply` del decide
  tool). Tras entregar la respuesta, cierra el ticket externo del helpdesk.
- Si el cliente vuelve a escribir en el mismo thread resuelto, se **reabre** (`open`,
  `resolved_at` NULL). Un tema nuevo suele llegar como thread nuevo del helpdesk (otro
  `external_id` → conversación nueva → resolución nueva potencial).
- Invariante: `resolved_at IS NOT NULL  <=>  status='resolved'`. Hay índice parcial
  `(tenant_id, resolved_at)` para el conteo por periodo.

### 2.2 Conteo por periodo (PR #234)
- **No** un contador mutable que se "resetea": se cuenta por **evento** en el log append-only
  `resolution_events` (tenant_id, conversation_id, resolved_at, reverted_at).
- `conversations.resolved_at` es estado operativo; `resolution_events` es billing-grade:
  permite contar y revertir a través de periodos sin perder histórico.
- El periodo es mensual y se ancla a `period_anchor_day` de la suscripción
  (`current_period_bounds`).

### 2.3 Ventana de reapertura (subtract vs nueva)
Edge case "el cliente vuelve días después" en el **mismo** thread resuelto
(`reopen_window_days`, default 7):
- **Dentro** de la ventana → se reabre y se **descuenta** esa resolución (`reverted_at`).
- **Fuera** de la ventana → cuenta como **nueva** resolución aunque reuse el thread.
- La mecánica de estado reabre siempre igual; la distinción subtract-vs-nueva es **solo para el
  conteo de billing**.

---

## 3. Estado de la implementación

| Pieza | Estado |
|---|---|
| `resolved` / `resolved_at` + reapertura | ✅ #196 |
| `resolution_events` + conteo con ventana + `GET /usage` + `PUT /subscription` | ✅ #234 (migración por aplicar en staging) |
| Stripe (subscription = suelo, metered = overage) + tablas de cobro | ⏭️ pendiente |
| Vista de uso en el dashboard del cliente (resoluciones del periodo vs incluido) | ⏭️ pendiente |

---

## 4. Catálogo de tiers (defaults del código)

`BILLING_TIERS` en `services/billing.py`. Son **defaults para crear suscripciones**: cada
suscripción guarda su propio snapshot de floor/included/overage, así que cambiar el catálogo no
altera suscripciones existentes. `founding` no tiene defaults (valores explícitos por cliente).
Los números son **provisionales**.

| Tier | Suelo mensual | Resoluciones incluidas | Overage/resolución |
|---|---:|---:|---:|
| starter | 890 € | 1.000 | 0,25 € |
| growth | 2.490 € | 3.000 | 0,25 € |
| scale | 5.990 € | 10.000 | 0,20 € |
