# Aprobaciones L3

Las acciones destructivas de Shopify (reembolso, cancelación, cambio de dirección, devolución) no se ejecutan solas: el agente propone, queda una aprobación pendiente y un humano la aprueba o la rechaza en el dashboard.

## Sub-features

- `approval-pending` una petición L3 válida crea una aprobación pendiente y el agente avisa que pasa al equipo (el gate exige que el email del comprador sea el del pedido).
- `approval-reject` rechazar desde el dashboard cierra la aprobación **sin ejecutar** nada en Shopify.
- `approval-approve` aprobar ejecuta la skill L3 en Shopify. **No se automatiza** (ver Gotchas).

## How to get to it (user POV)

- Super_admin: `/tenants/<tenantId>/approvals`. Cliente: `/clients/<tenantId>/approvals`. h1 `Aprobaciones`, pestañas `Pendientes / Aprobadas / Rechazadas / Todas`. Cada tarjeta muestra la acción (p. ej. `Iniciar devolución`), el motivo, el pedido y el procedimiento, con los botones `Aprobar` y `Rechazar`; `Rechazar` abre el diálogo `Rechazar acción` con el campo `Motivo del rechazo…`.

## Driving it with scripts/ + Playwright

Preconditions:

- `doctor.sh` sin `FAIL`, API y web locales arriba, sesión super_admin guardada.
- La cola de `marea-studio` **sin otras aprobaciones pendientes**: el driver se niega a actuar si ve más de una.
- Pedido de la demo de Marea: `#1431` (Blusa Satinada + Bolso Bandolera, pagado y enviado el 2026-09-30) del email `carmenrosavegas@hotmail.com`. Estado de los otros: `#1430` reembolso parcial, `#1432` y `#1433` reembolsados. Si Shopify cambió, léelo con el paso 1.

- **1. Identificar al comprador.** El email del payload **no** se usa para buscar pedidos; hay que decirlo en el mensaje. `VERIFY_EMAIL=carmenrosavegas@hotmail.com .claude/skills/verify/scripts/inbound.sh marea-studio "Hola, mi email es carmenrosavegas@hotmail.com. Quiero devolver el pedido #1431, me queda pequeño."`. `decision: respond`; el agente confirma que está dentro del plazo y pregunta qué artículo. Guarda el `conversation_id`.
- **2. Concretar y disparar el L3.** `VERIFY_EMAIL=carmenrosavegas@hotmail.com .claude/skills/verify/scripts/inbound.sh marea-studio "Solo la Blusa Satinada, por favor. El motivo es que la talla me queda pequeña." <conversation_id>`. `decision: escalate` con `escalation_reason: awaiting_human_approval:<approval_id>` y una respuesta que dice que lo pasa al equipo.
- **3. Confirmar la aprobación pendiente.** `.claude/skills/verify/scripts/db.sh "select id, aop_slug, skill_slug, skill_tier, status from pending_approvals where conversation_id='<conversation_id>' and deleted_at is null"`. Una fila: `returns | shopify.start_return | L3 | pending`.
- **4. Verla en el dashboard y rechazarla.** `node .claude/skills/verify/scripts/web-reject-approval.cjs 683246c2-10ce-4f6c-a299-5053f32f8c01 "Verificación automática: rechazo de prueba, no ejecutar."`. Guarda tres capturas (`approval-reject-1-pending/2-dialog/3-after`); la primera muestra la tarjeta `Iniciar devolución` con `Motivo: size_too_small`.
- **5. Confirmar el rechazo.** Repite el `select` del paso 3: `status = rejected` y el `review_comment` enviado. Comprueba que Shopify no se tocó: `db.sh "select skill_slug, status from skill_audit_log where conversation_id='<conversation_id>' order by created_at"` muestra `shopify.start_return | rejected_by_permissions` y ninguna ejecución exitosa.

## Gotchas

- **Aprobar es irreversible en Shopify.** `web-reject-approval.cjs` nunca pulsa `Aprobar` y se niega a actuar si no hay exactamente 1 pendiente. Aprobar solo con OK explícito de Kenny, a mano.
- Si describes un defecto ("llegó con un hilo suelto"), el AOP es `complaint` y **escala sin crear aprobación** (probado). Para una aprobación L3 usa un motivo de devolución (`talla`) o un cambio de dirección/cancelación.
- El agente hace dos turnos (identificar y concretar artículo) antes del L3; un solo mensaje no basta.
- Sin el email/teléfono correcto el gate bloquea (`phone_mismatch`/ownership) y no crea aprobación: es el comportamiento correcto.
- La conversación de prueba queda en staging con una escalación abierta (`awaiting_human_approval:…`); no la resuelvas sin avisar a Kenny.
- Probado el 2026-10-11 (pasos 1-5, `marea-studio`).
