# Conocimiento y hechos del tenant

El cliente envía su base de conocimiento (KB) y edita sus datos factuales (`tenant_facts`); el agente los usa en las respuestas. Es lo único que el cliente configura. La vista del cliente es de un `tenant_admin`; el super_admin solo ve la cola de revisión.

## Sub-features

- `kb-client` vista del cliente: contadores `En revisión / Procesado / Rechazado`, formulario `Aportar conocimiento` y lista `Últimos envíos`.
- `facts-client` pestaña `Datos factuales` de la misma página.
- `kb-review-admin` cola de revisión del super_admin (h1 `KB pending review`).
- `kb-in-answer` un cambio en KB/hechos se refleja en la respuesta del agente.

## How to get to it (user POV)

- Cliente (tenant_admin): `/clients/<tenantId>/knowledge`. `/clients/<tenantId>/facts` **redirige a la misma página** (los datos factuales son una pestaña, no una ruta).
- Super_admin: `/tenants/<tenantId>/knowledge`. Con un super_admin las rutas `/clients/...` redirigen a `/` (el layout exige `tenant_admin` con `tenant_id`).

## Driving it with Playwright (scripts/web-shot.cjs)

Preconditions:

- `doctor.sh` sin `FAIL`: **API y web locales arriba**. Para la vista del cliente, sesión del perfil `tenant` (`VERIFY_PROFILE=tenant`, usuario `kennyrmv@gmail.com`, tenant_admin de `marea-studio`).

- **Vista del cliente.** `VERIFY_PROFILE=tenant node .claude/skills/verify/scripts/web-shot.cjs /clients/683246c2-10ce-4f6c-a299-5053f32f8c01/knowledge client-kb`. El `.txt` muestra `Base de conocimiento`, `En revisión 0 / Procesado 1 / Rechazado 0`, el formulario `Aportar conocimiento` (`Título`, `URL de origen`, `Archivo de texto o markdown`, `Notas para Auyan`, botón `Enviar`) y `Últimos envíos` con `conocimiento general · Procesado`. 0 errores de consola.
- **Datos factuales.** La misma página con la pestaña `Datos factuales`; contrasta con `.claude/skills/verify/scripts/db.sh "select key, value from tenant_facts where tenant_id='683246c2-10ce-4f6c-a299-5053f32f8c01' and deleted_at is null"`.
- **Cola del super_admin.** `node .claude/skills/verify/scripts/web-shot.cjs /tenants/683246c2-10ce-4f6c-a299-5053f32f8c01/knowledge kb-review`. h1 `KB pending review`; vacía muestra `No hay contenido pendiente.`
- **Efecto en el agente.** Tras un cambio autorizado, repite `agent-respond` con una pregunta cuyo dato salga de ese hecho y comprueba que la respuesta lo refleja.

## Gotchas

- Con `/clients/...` sin la API local arriba, la página da `ERR_TOO_MANY_REDIRECTS` (bucle `/` ↔ `/login`): no es un problema de sesión.
- La KB se indexa con embeddings (`knowledge_base_chunks`): un documento recién enviado puede tardar en ser recuperable; confirma que hay chunks antes de preguntar.
- `RAG_MIN_SIMILARITY` filtra: una pregunta lejana del texto del documento no lo recuperará.
- Enviar un documento o editar un hecho **modifica la base de Marea** (que usan los E2E): solo con OK de Kenny. Este mapa solo prueba la lectura.
- Probado el 2026-10-11 (lectura): vista del cliente, redirección de `/facts` y cola del super_admin. Sin probar: enviar conocimiento, editar hechos y `kb-in-answer`.
