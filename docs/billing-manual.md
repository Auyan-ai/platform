# Auyan — Billing manual para primeros clientes

Fuente estratégica: `docs/auyan-master-context.md`. Este runbook cubre Bloque 1.10: primeros 1–2 clientes con factura manual + transferencia. Stripe Subscriptions, Stripe Tax, cupones y webhooks quedan fuera del MVP técnico y pasan a Bloque 2.

---

## Política comercial base

### Founding Partner

- Setup: gratis.
- Mes 1: gratis.
- Meses 2–6: 690 €/mes.
- Mes 7+: 890 €/mes si el cliente queda en Starter.
- Condición esperada: feedback frecuente, acceso a conversaciones reales y permiso para caso de estudio si los resultados acompañan.

### Tiers de referencia

| Tier | Setup | Mensual | Tickets incluidos | Cliente típico |
|---|---:|---:|---:|---|
| Starter | Gratis | 890 € | 1.500 | 2–5 personas CX, 500–1.500 tickets/mes |
| Growth | 1.500 € | 2.490 € | 5.000 | 5–15 personas CX, 2–5K tickets/mes |
| Scale | 4.000 € | 5.990 € | 15.000 | 15–30 personas CX, 5–15K tickets/mes |

Overage de referencia: 0,15–0,30 €/ticket extra según tier. Para los primeros 1–2 clientes, cualquier overage debe acordarse manualmente antes de facturarlo.

---

## Checklist por cliente

Antes de enviar la primera factura:

1. Cliente legal/fiscal confirmado.
2. Tier, descuento y periodo gratuito acordados por escrito.
3. Contacto de facturación confirmado: nombre, email y datos fiscales.
4. Contacto operativo confirmado: nombre, email y rol.
5. Método de pago: transferencia bancaria.
6. Fecha de inicio de servicio y fecha de primera factura confirmadas.
7. Condición Founding Partner, si aplica, documentada en el CRM o contrato.

Plantilla interna:

| Campo | Valor |
|---|---|
| Cliente |  |
| CIF/NIF/VAT |  |
| Dirección fiscal |  |
| Contacto facturación |  |
| Email facturación |  |
| Contacto operativo |  |
| Tier | Starter / Growth / Scale / FP |
| Setup acordado |  |
| Mensualidad acordada |  |
| Periodo gratis/descuento |  |
| Fecha inicio servicio |  |
| Fecha primera factura |  |
| Cuenta bancaria / método | Transferencia |
| Notas comerciales |  |

---

## Flujo manual

1. Crear o actualizar el registro comercial del cliente con el checklist completo.
2. Generar factura externa con el precio acordado.
3. Enviar factura al contacto de facturación desde el email operativo de Auyan.
4. Registrar fecha de envío, importe, vencimiento y estado de cobro.
5. Confirmar recepción o pago por transferencia.
6. Si pasan 7 días sin respuesta, enviar recordatorio manual.
7. Si pasan 14 días sin pago, revisar con el responsable comercial antes de pausar servicio.

Estados mínimos a mantener fuera del producto:

| Estado | Significado |
|---|---|
| `draft` | Datos preparados, factura aún no enviada. |
| `sent` | Factura enviada al contacto de facturación. |
| `paid` | Transferencia recibida o pago confirmado. |
| `overdue` | Vencimiento pasado sin pago confirmado. |
| `void` | Factura anulada o reemplazada. |

---

## Qué no construir todavía

- No crear tablas `billing_*` en Bloque 1.
- No integrar Stripe todavía.
- No automatizar impuestos, cupones ni overage metered.
- No mostrar billing al dashboard cliente hasta Bloque 2.

Bloque 2 puede convertir este runbook en producto con Stripe Subscriptions + Stripe Tax + cupón Founding Partner + webhooks + tablas `billing_*`.
