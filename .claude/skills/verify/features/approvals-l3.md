# Aprobaciones L3

Las acciones destructivas de Shopify (reembolso, cancelación, cambio de dirección, devolución) no se ejecutan solas: el agente propone, queda una aprobación pendiente y un humano la aprueba o la rechaza en el dashboard.

## Sub-features

- `approval-pending` una petición L3 válida crea una aprobación pendiente (el gate exige que el email/teléfono del comprador sea el del pedido).
- `approval-reject` rechazar cierra la aprobación **sin ejecutar** nada en Shopify.
- `approval-approve` aprobar ejecuta la skill L3 en Shopify.

## How to get to it (user POV)

- Super_admin: `/tenants/<tenantId>/approvals`. Cliente: `/clients/<tenantId>/approvals`. h1 `Aprobaciones`; el rechazo pide un motivo (`Motivo del rechazo…`).

## Driving it with scripts/ + Playwright

Preconditions:

- Un pedido de la tienda demo de Marea cuyo email conoces (pídeselo a Kenny o léelo con `db.sh`/Shopify; no lo inventes).
- Sesión de dashboard guardada (ver `inbox.md`).

- **Crear la aprobación.** `VERIFY_EMAIL=<email del pedido> .claude/skills/verify/scripts/inbound.sh marea-studio "Quiero un reembolso parcial del pedido #<n>"`. Esperado: la respuesta anuncia que queda pendiente de aprobación (no que ya se hizo); `dump.sh` no muestra ejecución.
- **Verla en la cola.** `node .claude/skills/verify/scripts/web-shot.cjs /tenants/683246c2-10ce-4f6c-a299-5053f32f8c01/approvals approvals-pending`. El `.txt` lista la aprobación.
- **Rechazar (camino seguro).** Rechazar desde el dashboard con un motivo; en Supabase la aprobación pasa a rechazada y Shopify no cambia. 
- **Aprobar.** Solo con OK explícito de Kenny: ejecuta una acción real sobre la tienda demo; verifícala después en Shopify.

## Gotchas

- Aprobar es irreversible en Shopify (reembolsos/cancelaciones). Por defecto, verifica `approval-pending` y `approval-reject`.
- Sin el email/teléfono correcto el gate bloquea (`phone_mismatch`/ownership) y no crea aprobación: eso es correcto, no un fallo.
- Un reembolso exige la transacción de cobro del pedido; en pedidos de prueba sin pago la skill falla.
- Probado el 2026-10-11: la cola `/tenants/<id>/approvals` carga con pestañas `Pendientes / Aprobadas / Rechazadas / Todas` y, sin pendientes, dice `No hay aprobaciones con estado "Pendientes".`.
- **Sin probar aún**: crear una aprobación (necesita el email de un pedido real de la demo) y rechazarla.
