# Auyan — Billing manual para primeros clientes

Fuente estratégica: `docs/auyan-master-context.md`. Este runbook cubre Bloque 1.10: primeros 1–2 clientes con factura manual + transferencia. Stripe Subscriptions, Stripe Tax, cupones y webhooks quedan fuera del MVP técnico y pasan a Bloque 2.

---

## Política comercial base

> **Estado:** pricing provisional. Los límites de tickets y precios se validan con los primeros Founding Partners antes de tratarlos como definitivos.

### Contexto de ICP y capacidad de pago

Los primeros clientes deben priorizar **Starter o Growth**: marcas con suficiente dolor para pagar, pero todavía con ciclos de compra rápidos y sin comités enterprise. Scale queda para cuando Auyan tenga historia, casos de estudio y operación más probada.

Referencia de tamaño para e-commerce Shopify/DTC español:

| Segmento | GMV/facturación anual aprox. | Tickets/mes aprox. | Tier natural | Lectura comercial |
|---|---:|---:|---|---|
| Bajo ICP | 1–2,5 M€ | 200–600 | No estándar / piloto limitado | Puede tener dolor, pero suele tener menos presupuesto y soporte menos formalizado. |
| Starter ICP | 2,5–5 M€ | 500–1.000 | Starter | Buen primer cliente si ya tiene helpdesk/equipo CX y dolor claro. |
| Growth ICP | 5–12 M€ | 1.500–3.000 | Growth | Sweet spot inicial: suficiente volumen, ROI claro, ciclo de venta aún razonable. |
| Scale ICP | 12–30 M€ | 3.000–10.000 | Scale | Buen negocio, pero requiere más confianza, referencias y madurez operativa. |
| Upper / Custom | 30 M€+ | 10.000+ | Custom | Revisar caso a caso; no prometer estándar. |

Ejemplos públicos para ponerle cara al ICP:

| Marca | Señal pública | Lectura para Auyan |
|---|---:|---|
| Scuffers | 2,5 M€ en 2022; luego crecimiento 225% YoY; Shopify; alto tráfico | Starter/Growth antes de escalar; buena referencia de DTC joven. |
| Yuxus | 3 M€ en 2023; objetivo 11 M€ en 2024; equipo joven | Growth temprano / Scale futuro. |
| Zapato Feroz | ~11 M€ facturación; ~130k pedidos/año; Shopify Plus; 100% online | Scale claro; buen arquetipo futuro. |
| Tropicfeel | 27 M€ en 2023 | Scale alto / Custom futuro. |
| Nude Project | 26 M€ en 2023; 130 empleados; 62% online | Scale alto; quizá demasiado grande para primeros clientes. |
| Freshly Cosmetics | 46,5 M€ en 2023; 300+ personas | Upper midmarket; fuera del foco inicial. |

Como porcentaje de facturación, Auyan debe sentirse pequeño frente al coste operativo que reduce:

| Facturación anual | Starter anual (10.680 €) | Growth anual (29.880 €) | Scale anual (71.880 €) |
|---:|---:|---:|---:|
| 3 M€ | 0,36% | 1,00% | 2,40% |
| 5 M€ | 0,21% | 0,60% | 1,44% |
| 10 M€ | 0,11% | 0,30% | 0,72% |
| 20 M€ | 0,05% | 0,15% | 0,36% |

Regla comercial: por debajo de ~2,5 M€ de facturación anual, Auyan solo entra si el dolor es muy claro, el founder decide rápido y el alcance está fuertemente limitado. No dejar que un cliente pequeño consuma operación managed completa.

### Rango bajo: opción táctica, no tier público

Para tiendas de **1–2,5 M€ de facturación anual** o **200–600 tickets/mes**, no crear un tier managed completo por defecto. Si aparece una marca pequeña pero estratégica, usar una oferta limitada:

| Opción | Precio orientativo | Alcance | Cuándo usar |
|---|---:|---|---|
| Founding Partner Lite | 390–490 €/mes | 3 meses, categorías muy acotadas, sin prometer operación completa | Caso de estudio potencial, founder decide rápido, datos reales accesibles. |
| Audit + Setup | 750–1.500 € one-off | Diagnóstico, playbook inicial, respuestas/AOPs base, handoff claro | Cliente sin volumen suficiente para retainer mensual. |
| No vender | 0 € | — | Sin helpdesk, sin equipo CX, sin dolor urgente o demasiada fricción operativa. |

Reglas:
- No publicarlo en pricing.
- No permitir más de 2–3h/mes de operación humana recurrente.
- No incluir custom integrations profundas.
- No aceptar si bloquea foco en Starter/Growth.
- Objetivo principal: aprendizaje, testimonio o puente hacia Starter; no MRR principal.

### Founding Partner

- Setup: gratis.
- Mes 1: gratis.
- Meses 2–6: 690 €/mes.
- Mes 7+: 890 €/mes si el cliente queda en Starter.
- Condición esperada: feedback frecuente, acceso a conversaciones reales y permiso para caso de estudio si los resultados acompañan.

### Tiers de referencia

| Tier | Setup | Mensual | Tickets incluidos | Cliente típico |
|---|---:|---:|---:|---|
| Starter | Gratis | 890 € | 1.000 | 2–4 personas CX, 500–1.000 tickets/mes |
| Growth | 1.500 € | 2.490 € | 3.000 | 4–10 personas CX, 1.500–3K tickets/mes |
| Scale | 4.000 € | 5.990 € | 10.000 | 10–25 personas CX, 3–10K tickets/mes |
| Custom | Custom | Custom | 10.000+ | Mid-market fuerte; revisar operación y margen antes de cotizar |

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
