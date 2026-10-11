# Vista del cliente

El `tenant_admin` de un cliente ve el estado de su agente, su actividad y lo que tiene pendiente, sin acceso a nada de otros tenants.

## Sub-features

- `client-overview` resumen: fase del agente, alertas, actividad reciente y reporte semanal.
- `client-conversations` / `client-escalations` / `client-approvals` listas de su tenant.
- `client-insights` / `client-reports` análisis y reportes.
- `client-settings` integraciones, branding, contacto y modelo del agente.
- `client-isolation` un `tenant_admin` no entra a otro tenant ni un super_admin a `/clients/...`.

## How to get to it (user POV)

- Tras iniciar sesión un `tenant_admin` cae en `/clients/<tenantId>/overview`. Menú: `Resumen`, `Insights`, `Reportes`, `Base de conocimiento`, `Aprobaciones`, `Configuración`.
- Rutas: `/clients/<tenantId>/{overview,conversations,escalations,approvals,knowledge,facts,insights,reports,settings,onboarding}`.

## Driving it with Playwright (scripts/web-shot.cjs)

Preconditions:

- `doctor.sh` sin `FAIL`, **API y web locales arriba**, sesión del perfil `tenant` (`VERIFY_PROFILE=tenant`).
- El tenant no está en lifecycle `initial`/`discovery` (si lo está, el layout manda a `/onboarding`). Marea está en `building`.

- **Cada página.** `VERIFY_PROFILE=tenant node .claude/skills/verify/scripts/web-shot.cjs /clients/683246c2-10ce-4f6c-a299-5053f32f8c01/<ruta> client-<ruta>` para `overview`, `conversations`, `escalations`, `approvals`, `knowledge`, `insights`, `reports`, `settings`. Las 8 cargan con 0 errores de consola.
- **Overview.** Muestra `Fase del agente` (Inicial → Activo), `Alertas` (`Aprobaciones L3 pendientes`, `Conversaciones escaladas`), `Resolución IA` y el aviso `El primer reporte aparecerá aquí cuando Auyan lo apruebe y envíe`. Contrasta los contadores con la base de datos.
- **Configuración.** `Integraciones`, `Branding` (`Marea Studio`, `Mercury light`), `Contacto asignado` y `Agente IA` (`claude-sonnet-4-6`, umbral de escalación `70%`).
- **Aislamiento en la UI.** Con el perfil `tenant`, abre `/clients/11111111-1111-1111-1111-111111111111/overview` (Lunaria), y también `/conversations` y `/approvals`: las tres terminan en `/clients/683246c2-…/overview` (el layout compara el `tenantId` de la URL con el del usuario).
- **Aislamiento en la API (lo importante).** `VERIFY_PROFILE=tenant node .claude/skills/verify/scripts/isolation.cjs 20430909-06cc-46d8-a81f-20e5187907d3 55555555-5555-5555-5555-555555555555` (una conversación de Marea y una de Lunaria). Con el token del `tenant_admin`: propia `200`, la de Lunaria `404`, `/tenants/admin/list` y `/tenants/admin/review-queue` `403`. Exit 1 si falla algo.

## Gotchas

- Sin la API local la página da `ERR_TOO_MANY_REDIRECTS`.
- `/clients/<id>/facts` redirige a `/knowledge`.
- Probado el 2026-10-11: las 8 páginas cargan y el aislamiento (UI y API) se comporta como se espera. Aprobaciones ajenas no se probaron (Lunaria no tiene ninguna viva).
