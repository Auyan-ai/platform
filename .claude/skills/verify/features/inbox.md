# Inbox del dashboard

El equipo interno (super_admin) o el tenant_admin ve las conversaciones del tenant, abre el detalle con el razonamiento del agente y atiende la cola de escalaciones.

## Sub-features

- `inbox-list` lista de conversaciones del tenant (h1 `Conversaciones`).
- `inbox-detail` detalle con mensajes y panel de razonamiento.
- `inbox-escalations` cola de escalaciones (h1 `Escalaciones`).

## How to get to it (user POV)

- Super_admin: `/tenants/<tenantId>/conversations`, `/tenants/<tenantId>/escalations`.
- Cliente (tenant_admin): `/clients/<tenantId>/conversations`, `/clients/<tenantId>/escalations`.
- Detalle: `/tenants/<tenantId>/conversations/<conversationId>`.

## Driving it with Playwright (scripts/web-shot.cjs)

Preconditions:

- `doctor.sh` sin `FAIL`, web local arriba (`up.sh web`), `profile/.logged-in` existe (`web-session.sh`; los drivers lo corren solos).
- Existe al menos una conversación de la corrida de `agent-respond` / `agent-escalate`.

- **Lista.** `node .claude/skills/verify/scripts/web-shot.cjs /tenants/683246c2-10ce-4f6c-a299-5053f32f8c01/conversations inbox-list`. El `.txt` contiene el h1 `Conversaciones` y la conversación de `VERIFY bot` con su política de devoluciones; 0 errores de consola.
- **Detalle.** `node .claude/skills/verify/scripts/web-shot.cjs /tenants/683246c2-10ce-4f6c-a299-5053f32f8c01/conversations/<conversationId> inbox-detail`. Se ven el mensaje del comprador, la respuesta del agente y los pasos de razonamiento (`shopify.get_shop_policies`).
- **Escalaciones.** `node .claude/skills/verify/scripts/web-shot.cjs /tenants/683246c2-10ce-4f6c-a299-5053f32f8c01/escalations inbox-escalations`. El h1 `Escalaciones` y la escalación del doble cobro con su motivo.

## Gotchas

- Sin sesión, todo redirige a `/login`: `web-shot.cjs` sale con código 3. No intentes escribir credenciales: corre `web-session.sh`; si falla, díselo a Kenny.
- El detalle usa TanStack Query: espera a que desaparezcan los esqueletos de carga antes de la captura (pasa un selector a `web-shot.cjs`).
- Los adjuntos (foto/audio) usan URL firmada de 5 min; no los cachees en la evidencia.
- Probado el 2026-10-11 con `kenny+admin@auyan.es` (rutas `/tenants/...`): lista (`Conversaciones`, con filtros Todas/Abiertas/Escaladas/…), detalle (mensajes cliente/Agente IA + panel `Agent reasoning`, 8 events) y `Escalaciones` (Pendiente / Tomar / Ver conversación). Las rutas `/clients/...` **no** se abren con super_admin (ver `knowledge-facts.md`).
- El panel `Agent reasoning` viene colapsado: para ver los eventos hay que expandirlo (no verificado con captura).
- Una conversación `Resuelta` es de solo lectura (`Conversación resuelta — sólo lectura`): no se puede responder desde ahí.
