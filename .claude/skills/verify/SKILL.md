---
name: verify
description: Levanta el API (FastAPI + grafo LangGraph) y el dashboard (Next.js) de Auyan desde el working tree contra el Supabase de STAGING, conduce el flujo real (webhook firmado → agente → respuesta/escalado → filas en Supabase) y captura evidencia. Úsalo para comprobar que un cambio en apps/api o apps/web funciona de verdad, no solo en tests.
---

# Verificar Auyan en vivo

Aquí no hay Supabase local (sin `supabase` CLI, sin Postgres, Docker sin permiso) aunque `apps/api/.env` y
`apps/web/.env.local` apunten a `127.0.0.1:54321`. Estos scripts ignoran esos dos archivos y cargan
`.env.staging` (raíz del repo, fuera de git) → **todo corre contra la DB de staging y usa LLM real (cuesta
centavos por turno)**. Tenant de pruebas: `marea-studio` (demo, sin datos reales). `lunaria` es el otro tenant de staging.
Nunca imprimas valores de `.env.staging` ni los pegues en la evidencia.

Todos los scripts están en `.claude/skills/verify/scripts/`. Ejecútalos desde cualquier carpeta.

## Doctor — corre esto primero, y cada vez que algo se vea raro

```bash
.claude/skills/verify/scripts/doctor.sh      # solo lectura; exit 1 si algo falla
```
Comprueba: rama/commit y cambios sin commitear, Supabase staging vivo (el free tier **se pausa tras 7 días
inactivo**), Cloud Run (informativo), API local (pid dueño del puerto 8000, `env=staging`, `db=true`, **worker
de cola apagado**), web local (`/login` 200) y si hay sesión de dashboard guardada. Las líneas `warn` no
bloquean; las `FAIL` sí.

## Launch

```bash
.claude/skills/verify/scripts/up.sh api      # uvicorn apps.api.main:app en :8000, listo cuando /health/ready da db=true (~10 s)
.claude/skills/verify/scripts/up.sh web      # next dev --turbopack en :3000 (~15 s la primera vez)
.claude/skills/verify/scripts/up.sh all
```
- Puertos fijos 8000/3000: `ALLOWED_ORIGINS` de staging solo admite `localhost:3000`. Si el puerto está
  ocupado por algo que **no** arrancó este skill, `up.sh` se niega (no hay doble drive sobre una instancia ajena).
- `up.sh` fuerza `INBOUND_WORKER_CONCURRENCY=0` y `CLEANUP_INTERVAL_SECONDS=86400`. Motivo: la API local y
  Cloud Run comparten la tabla `inbound_jobs`; con el worker encendido, el proceso local **robaría jobs reales
  de Zendesk/Gorgias/Chatwoot de staging y los respondería con código sin desplegar**. No lo quites.
- La web recibe `NEXT_PUBLIC_SUPABASE_URL/ANON_KEY` de staging y `NEXT_PUBLIC_API_URL=http://localhost:8000` por
  entorno del proceso (gana a `apps/web/.env.local`).
- **La web necesita la API local.** El dashboard le pregunta a `localhost:8000/users/me` quién es el usuario; sin API, toda página
  entra en un bucle `/` ↔ `/login` (`ERR_TOO_MANY_REDIRECTS`) y parece "sesión expirada". Levanta siempre `up.sh all`.
- Logs: `.claude/skills/verify/run/api.log` y `web.log`. Pidfiles en `run/`.

## Drive

### API / agente (sin login, es el camino principal)
```bash
.claude/skills/verify/scripts/inbound.sh marea-studio "Hola, ¿cuál es vuestra política de devoluciones?"
.claude/skills/verify/scripts/inbound.sh marea-studio "otro mensaje" <conversation_id>   # multi-turno
```
Envía un webhook firmado (HMAC con `WEBHOOK_SECRET`) a `POST /webhooks/inbound`, `channel=chat`. Ese endpoint
corre el grafo **dentro del request** y devuelve la respuesta en el body: `decision` (`respond` | `escalate`),
`response_text`, `escalation_reason`, `trace_id`, `conversation_id`. No entrega nada a un helpdesk real y no
pasa por la cola. Cada llamada crea un cliente `VERIFY bot` / `verify-<timestamp>@example.com` en staging.
Con `--channel` distinto (zendesk, chatwoot…) sí hay entrega externa: no lo uses aquí.

Lado Supabase de una conversación (mensajes, eventos de razonamiento, escalaciones):
```bash
.claude/skills/verify/scripts/dump.sh <conversation_id>
.claude/skills/verify/scripts/db.sh "select ..."      # psql de SOLO LECTURA contra staging
```
Tablas útiles: `conversations`, `messages`, `agent_reasoning_events` (seq/phase/label), `escalations`,
`skill_audit_log`, `tenant_usage_daily`, `aops`, `tenant_facts`, `knowledge_base_chunks`.

### Dashboard (Playwright)
El login es email+contraseña de Supabase y **el agente no escribe contraseñas**. La sesión se crea sola, sin contraseña, solo contra staging:
```bash
.claude/skills/verify/scripts/web-session.sh                      # super_admin (kenny+admin@auyan.es) -> profile/
VERIFY_PROFILE=tenant .claude/skills/verify/scripts/web-session.sh   # tenant_admin de Marea (kennyrmv@gmail.com) -> profile-tenant/
```
`web-session.cjs` usa la `SUPABASE_SERVICE_ROLE_KEY` de `.env.staging`: admin `generate_link` -> canje del `token_hash` en `/auth/v1/verify` -> escribe la cookie `sb-<ref>-auth-token` en el perfil. No pasa por `/auth/callback` (que cierra la sesión del super_admin a propósito desde #287/#311), así que no cambia ninguna regla de la web ni del API y no abre nada en producción. Se niega si `SUPABASE_URL` o la service role no son del proyecto `johidurhcobdkpvlnowl`, y nunca imprime token, enlace ni key (sí el usuario usado y su rol). `web-shot.cjs` y los demás drivers lo invocan solos al caer en `/login` y repiten el comando una vez; solo salen con código 3 si la renovación falla (¿staging pausado? ¿usuario borrado?). `web-login.sh` (login manual de Kenny) queda como último recurso.
Hay dos perfiles de navegador, uno por rol. Sin variable es el **super_admin** (`profile/`, rutas `/tenants/...`). Con
`VERIFY_PROFILE=tenant` es un **tenant_admin** de Marea (`profile-tenant/`, rutas `/clients/...`):
```bash
VERIFY_PROFILE=tenant .claude/skills/verify/scripts/web-login.sh   # Kenny, una vez, con el usuario tenant_admin de Marea
VERIFY_PROFILE=tenant node .claude/skills/verify/scripts/web-shot.cjs /clients/<id>/facts facts
```
El login guarda las cookies en el perfil y en `state.json`, que cada corrida restaura (Chromium se lanza con `--password-store=basic`;
con el llavero del escritorio, la clave de cifrado de las cookies podía variar entre la ventana de login y una corrida headless).
Si una página da "sesión expirada" o un bucle de redirecciones, **mira primero que la API local esté arriba** antes de pedir otro login.
Después, el agente conduce con la sesión guardada:
```bash
node .claude/skills/verify/scripts/web-shot.cjs /tenants/683246c2-10ce-4f6c-a299-5053f32f8c01/conversations conversaciones
node .claude/skills/verify/scripts/web-shot.cjs <ruta> <nombre> '<selector a esperar>'
```
Escribe `evidence/<ts>-<nombre>.png` y `.txt` (texto visible + errores de consola). Si la sesión expiró la renueva sola (`web-session.cjs`); sale con código 3 solo si la renovación falla. Playwright lo instala mise (`~/.local/share/mise/installs/npm-playwright`)
y espera un build de Chromium más nuevo que el del caché; `_pw.cjs` usa el Chromium que ya hay en `~/.cache/ms-playwright`
(`PW_CHROMIUM` lo sobreescribe). No descargues browsers sin avisar.
Rutas super_admin: `/tenants/<id>/{conversations,escalations,approvals,playbook,knowledge,reports,emails,aops,proposals,simulator}`;
rutas del cliente: `/clients/<id>/{overview,conversations,escalations,approvals,facts,knowledge,insights,reports,settings,onboarding}`.
IDs: `marea-studio` = `683246c2-10ce-4f6c-a299-5053f32f8c01`, `lunaria` = `11111111-1111-1111-1111-111111111111`.
Sin sesión, cualquier ruta redirige a `/login` (middleware). La sesión guardada es la de `kenny+admin@auyan.es`: abre `/tenants/...`; las rutas `/clients/...` exigen rol `tenant_admin` y a un super_admin lo mandan a `/`.
`web-shot.cjs` no cuenta el 404 de `/favicon.ico` (apps/web no tiene favicon); cualquier otro 4xx/5xx o error de consola sí se lista.

## Evidence

Todo va a `.claude/skills/verify/evidence/` (con timestamp). Una prueba válida incluye:
1. **La acción**: el mensaje enviado y la respuesta HTTP cruda (`inbound.sh` ya lo guarda).
2. **El estado resultante en Supabase** (`dump.sh`): mensaje `customer` inbound + `agent_ai` outbound, eventos
   de razonamiento (qué skill/tool llamó, por qué decidió), escalación con `reason` si hubo escalado.
3. **El estado visible** en el dashboard si el cambio toca la UI (`web-shot.cjs`), con 0 errores de consola.
4. **Trace**: `.claude/skills/verify/scripts/trace.sh <trace_id>` confirma que el `trace_id` de la respuesta existe
   en LangSmith (proyecto `auyan-staging`, `agent_conversation`, status `success`). CLAUDE.md exige que todo turno
   tenga trace y correlación con Supabase.

Estándares: recorre el camino real del usuario (webhook firmado / navegador), no funciones internas ni
endpoints de test; verifica efectos secundarios (filas, escalaciones) además de lo visible; los mocks solo
donde ya hay una frontera de producción (Shopify/helpdesks son los de staging, no se simulan aquí).
Un `dry-run` se verifica observando (filas/red/logs), no fiándose del nombre.

## Cleanup

```bash
.claude/skills/verify/scripts/down.sh     # para solo los grupos de procesos de run/*.pid; evidence/ y profile/ no se tocan
```
Nunca mates por nombre de proceso (`pkill uvicorn`/`next`): puede haber instancias ajenas. Confirma con
`doctor.sh` que no quedan `api`/`web` locales. Las conversaciones de prueba se quedan en staging (clientes
`VERIFY bot`); si hay que retirarlas es **soft delete** (`deleted_at`) y solo con OK explícito de Kenny.

## Mapa de features

`features/README.md` indexa lo verificable (agente → respuesta, escalado, inbox, aprobaciones L3, conocimiento/hechos).
Tests de las salvaguardas del mint: `node --test .claude/skills/verify/scripts/web-session.test.cjs`.
`isolation.cjs <conv propia> <conv ajena>` prueba el aislamiento de tenant en la API con el token del tenant_admin.
`web-reject-approval.cjs <tenantId> "<motivo>"` rechaza la única aprobación L3 pendiente (nunca aprueba; ver `features/approvals-l3.md`).
`web-facts.cjs` (editar un hecho), `web-kb-submit.cjs` (enviar KB como cliente) y `web-kb-review.cjs` (aprobar/rechazar KB como super_admin) **modifican Marea**: solo con OK de Kenny y dejándolo como estaba (ver `features/knowledge-facts.md`).
Una prueba que solo conduce un punto de entrada cuando el mapa lista varios está incompleta: cúbrelos o di cuáles no.
