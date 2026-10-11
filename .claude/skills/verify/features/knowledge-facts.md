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
- **Datos factuales.** La misma página con la pestaña `Datos factuales`; contrasta con `.claude/skills/verify/scripts/db.sh "select data, version from tenant_facts where tenant_id='683246c2-10ce-4f6c-a299-5053f32f8c01'"` (una fila por tenant, todo en el JSONB `data`, sin `deleted_at`).
- **Cola del super_admin.** `node .claude/skills/verify/scripts/web-shot.cjs /tenants/683246c2-10ce-4f6c-a299-5053f32f8c01/knowledge kb-review`. h1 `KB pending review`; vacía muestra `No hay contenido pendiente.`

### Escritura y efecto en el agente (`kb-in-answer`) — modifica Marea, solo con OK de Kenny

**Hechos** (se leen en cada turno, sin caché):
1. Línea base: `.claude/skills/verify/scripts/inbound.sh marea-studio "Hola, ¿en qué horario atendéis?"` → "lunes a viernes de 8 a 16 horas".
2. Editar como cliente: `VERIFY_PROFILE=tenant node .claude/skills/verify/scripts/web-facts.cjs 683246c2-10ce-4f6c-a299-5053f32f8c01 business_hours "lunes a viernes de 9 a 17 horas"`. Imprime el valor anterior; el `select` de arriba muestra el nuevo valor, `version` +1 y los campos extra (`company_name`, `primary_contact`) intactos.
3. Repetir el paso 1 en una conversación nueva → la respuesta dice 9 a 17.
4. **Restaurar** con el valor que imprimió el paso 2 y repetir el paso 1 → vuelve a 8 a 16.

**KB** (cliente envía → super_admin aprueba → se indexa):
1. Línea base con algo que la KB no tenga (`db.sh` con `content ilike '%regalo%'` sobre los chunks vivos → 0): `inbound.sh marea-studio "¿Las tarjetas regalo caducan? ¿Cuánto duran?"` → `escalate` (`low_confidence` o "no hay información").
2. Enviar como cliente: `VERIFY_PROFILE=tenant node .claude/skills/verify/scripts/web-kb-submit.cjs 683246c2-10ce-4f6c-a299-5053f32f8c01 "VERIFY tarjetas regalo" "<texto con un dato comprobable, p. ej. caducan a los 12 meses>"`. Queda `pending_review` en `tenant_knowledge_submissions` y en `En revisión`.
3. Aprobar como super_admin: `node .claude/skills/verify/scripts/web-kb-review.cjs 683246c2-10ce-4f6c-a299-5053f32f8c01 "VERIFY tarjetas regalo" approve` (o `reject`, que no indexa nada). Crea una fila en `knowledge_base_documents` con sus chunks; el embedding es síncrono, se puede preguntar al momento.
4. Repetir el paso 1 → `respond` con el dato del documento; `trace.sh` del `trace_id` → `success`.
5. **Retirar:** soft delete (`deleted_at = now()`) del `knowledge_base_documents` y del `tenant_knowledge_submissions` de prueba, con psql de escritura (`db.sh` es de solo lectura). El RAG filtra `d.deleted_at IS NULL`; repetir el paso 1 → vuelve a escalar y la vista del cliente vuelve a sus contadores.

## Gotchas

- Con `/clients/...` sin la API local arriba, la página da `ERR_TOO_MANY_REDIRECTS` (bucle `/` ↔ `/login`): no es un problema de sesión.
- La KB se indexa con embeddings (`knowledge_base_chunks`): un documento recién enviado puede tardar en ser recuperable; confirma que hay chunks antes de preguntar.
- `RAG_MIN_SIMILARITY` filtra: una pregunta lejana del texto del documento no lo recuperará.
- Enviar un documento o editar un hecho **modifica la base de Marea** (que usan los E2E): solo con OK de Kenny, y siempre se deja como estaba (hecho restaurado, documento con soft delete).
- `agent_reasoning_events` no registra la recuperación de la KB (solo `Load context` y la decisión): la prueba de que usó el documento es el contraste con la línea base.
- `web-kb-review.cjs` se niega si no hay exactamente un pendiente con ese título.
- Probado el 2026-10-11: lectura (vista del cliente, redirección de `/facts`, cola del super_admin) y escritura completa (hecho editado y restaurado, documento enviado, aprobado, usado por el agente y retirado).
