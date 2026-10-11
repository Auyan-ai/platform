# Conocimiento y hechos del tenant

El cliente sube su base de conocimiento (KB) y edita sus `tenant_facts`; el agente los usa en las respuestas. Es lo único que el cliente configura.

## Sub-features

- `kb-list` lista de documentos de la base de conocimiento (h1 `Base de conocimiento`).
- `facts-edit` edición de hechos del tenant en `/clients/<id>/facts`.
- `kb-in-answer` un cambio en KB/hechos se refleja en la respuesta del agente.

## How to get to it (user POV)

- Cliente: `/clients/<tenantId>/knowledge` y `/clients/<tenantId>/facts`. Super_admin: `/tenants/<tenantId>/knowledge` (h1 `KB pending review`).

## Driving it with scripts/ + Playwright

Preconditions:

- Sesión de dashboard guardada. Mutaciones: solo con OK de Kenny (tenant demo, pero es la base que usan los E2E).

- **Ver la KB.** `node .claude/skills/verify/scripts/web-shot.cjs /clients/683246c2-10ce-4f6c-a299-5053f32f8c01/knowledge kb-list`. El `.txt` lista documentos y estado.
- **Ver los hechos.** `node .claude/skills/verify/scripts/web-shot.cjs /clients/683246c2-10ce-4f6c-a299-5053f32f8c01/facts facts`. Contrasta con `db.sh "select key, value from tenant_facts where tenant_id='683246c2-10ce-4f6c-a299-5053f32f8c01' and deleted_at is null"`.
- **Efecto en el agente.** Tras un cambio autorizado, repite `agent-respond` con una pregunta cuyo dato salga de ese hecho y comprueba que la respuesta lo refleja.

## Gotchas

- **`/clients/<id>/...` exige un `tenant_admin` con `tenant_id`** (el layout redirige a `/` a cualquier otro rol). Con `super-admin@auyan.ai` esas rutas caen en `Review Queue` (`/`): no son verificables con la sesión actual. Hace falta un segundo perfil de Playwright con un usuario `tenant_admin` de Marea (`web-shot.cjs` aún no soporta elegir perfil).
- Lo que sí abre el super_admin: `/tenants/<id>/knowledge` (h1 `KB pending review`, hoy cola vacía: `No hay contenido pendiente.`) y `/tenants/<id>/playbook`.
- La KB se indexa con embeddings (`knowledge_base_chunks`): un documento recién subido puede tardar en ser recuperable; confirma que hay chunks antes de preguntar.
- `RAG_MIN_SIMILARITY` filtra: una pregunta lejana del texto del documento no lo recuperará.
- **Sin probar aún**: la vista del cliente (KB, hechos) y el efecto de un cambio de hechos en la respuesta del agente.
