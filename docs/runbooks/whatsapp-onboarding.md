# Runbook — Alta de WhatsApp (Zernio) para un tenant

> Doc vivo. Diseño: [ADR 0010](../adr/0010-whatsapp-zernio-handoff.md). Plan: [whatsapp-zernio-plan.md](../whatsapp-zernio-plan.md).
> Fuente reproducible: `apps/api/scripts/onboard_whatsapp.py`. Lo que se haga a mano con el
> MCP de Zernio se repite después con el script.

## Requisitos

- `.env.staging` (o el de producción) con `DATABASE_URL`, `INTEGRATIONS_SECRET_KEY` y
  `AUYAN_API_BASE_URL` (URL pública de la API).
- `.env.zernio` **aparte**, local y fuera de git, con `ZERNIO_API_KEY` (**key maestra** de la
  cuenta de Auyan en Zernio: solo scripts de operación, **nunca** el runtime). ⚠️ **No** la pongas
  en `.env.staging`: `deploy_cloud_run.sh` sube todas sus variables a Cloud Run.
- Red: la política del entorno cloud bloquea `zernio.com` por defecto. Para correr el script
  desde una sesión, añadir `zernio.com` a los dominios permitidos del entorno.
- Migración `20261001000001_add_zernio_channel.sql` aplicada (y las del Sprint 2 que falten,
  ver "🔴 Producción" en `docs/progress.md`).
- Desde `apps/api`: `set -a; . ../../.env.staging; . ../../.env.zernio; set +a`.

## 1. Con el cliente (antes del script)

1. **Meta Business Portfolio** verificado (o en verificación) y método de pago en la WABA para
   las conversaciones de plantilla (confirmar en C0 quién paga a Meta).
2. Decidir número:
   - **Coexistence** (el número ya usa la app WhatsApp Business): el cliente sigue contestando
     desde el móvil; cuando lo hace, Auyan se calla 12 h (configurable por tenant con
     `tenant_config.extra.whatsapp_device_hold_hours`).
   - **Número nuevo**: solo Cloud API (Auyan + helpdesk).
3. El cliente debe tener el helpdesk conectado en Auyan (hoy: **Zendesk** como helpdesk
   primario) para el handoff. Sin helpdesk primario, los escalados solo quedan en el dashboard.

## 2. Preparar (profile, key limitada, webhook)

```bash
python -m scripts.onboard_whatsapp prepare --tenant <slug> --brand "<Marca>" --dry-run
python -m scripts.onboard_whatsapp prepare --tenant <slug> --brand "<Marca>"
```

Crea (o reusa) el profile `auyan-<slug>`, una API key **limitada a ese profile** y el
webhook firmado hacia `…/webhooks/zernio`. Guarda la integración **inactiva** e imprime el
enlace del **signup hospedado** (co-branded, en español). Mándaselo al cliente.

`--onboarding {business_app,api}` (solo `prepare`): `business_app` (por defecto) ofrece
coexistence con la app WhatsApp Business; `api` es solo Cloud API (número nuevo o ya en Cloud
API, grupos o llamadas). Se pasa tal cual a `GET /v1/connect/whatsapp`.

### Idempotencia y dry-run (todos los subcomandos)

Cada paso lee primero el estado actual (Zernio y Supabase) y solo crea lo que falta. Se puede
repetir cualquier subcomando tras un fallo a medias; repetir uno que ya terminó no crea nada.
Al final imprime un resumen por paso: `created`, `reused`, `skipped` o `deleted`.

| Paso | Cómo detecta que ya existe |
|---|---|
| profile | `config.profile_id` guardado; si falta, busca `auyan-<slug>` en `GET /profiles` |
| api_key | `api_key` + `config.api_key_id` guardados y presentes en `GET /api-keys` (por nombre `auyan-<slug>-runtime`/`-sandbox`) |
| webhook | `config.webhook_id` + `webhook_secret` guardados y presentes en `GET /webhooks/settings` (nombre `auyan-<slug>`) |
| signup_link | si `GET /accounts` ya trae WhatsApp, se omite (corre `finalize`) |
| integration / template (`finalize`) | estado guardado igual a la cuenta leída; plantilla en `GET /whatsapp/templates` |

- **Sin huérfanos.** Cada recurso remoto se guarda en Supabase nada más crearse (ya no hay una
  transacción envolvente que lo revierta). Si el guardado falla, el script borra el recurso
  que acaba de crear y lo dice. Una key o webhook con nuestro nombre y sin valor guardado es
  huérfano (Zernio no devuelve el valor): se borra y se recrea. `--rotate-key` crea la nueva,
  la guarda y solo entonces borra la anterior.
- **`--dry-run`** hace solo lecturas y muestra, paso a paso, qué se crearía, reutilizaría o
  borraría. Cualquier escritura en dry-run se bloquea en el cliente.
- **Secretos.** `GET /v1/api-keys` devuelve la key maestra en claro (`firstApiKey`): el script
  solo conserva id, nombre, scope y profileIds, y nunca imprime cuerpos de esos endpoints.
- Si el listado de Zernio llega con una forma inesperada, el script se detiene sin tocar nada.

## 3. El cliente completa el Embedded Signup

Con el enlace: login de Facebook → portfolio → número (coexistence o nuevo) → verificación
por SMS/llamada. Un WhatsApp por profile.

## 4. Finalizar

```bash
python -m scripts.onboard_whatsapp finalize --tenant <slug> --dry-run
python -m scripts.onboard_whatsapp finalize --tenant <slug>
```

Lee la cuenta de WhatsApp del profile, guarda `account_id` y el teléfono, **activa** la
integración y crea la plantilla `auyan_reengagement` (UTILITY, `es`):

> Hola {{1}}, tenemos una respuesta sobre tu consulta. Responde a este mensaje para verla.

Queda **pendiente de aprobación de Meta** (minutos a horas). Mientras no esté aprobada, las
respuestas fuera de la ventana de 24 h fallan y se registran como `failed` + nota interna.

## 5. Handoff en Zendesk (triggers)

```bash
python -m scripts.setup_zendesk_handoff_triggers --tenant <slug> --dry-run
python -m scripts.setup_zendesk_handoff_triggers --tenant <slug>
```

Crea (idempotente) los triggers **"Auyan · handoff · respuesta"** y **"Auyan · handoff ·
resuelto"** hacia el webhook de Zendesk ya existente, y añade al trigger de inbound la
condición `tags no incluye auyan_handoff`. Guarda `api_user_id` en la config de Zendesk
(el usuario API de Auyan, cuyos comentarios nunca se reenvían).

## 6. Verificación

Primero el **doctor**, que comprueba en vivo todo lo que se puede comprobar sin un mensaje
real: migraciones aplicadas, helpdesk primario con handoff, firma, webhook y triggers de
Zendesk contra su definición canónica, credenciales y salud de la cuenta en Meta
(`GET /v1/accounts/{id}/health`), plantilla de re-enganche y cola de turnos. Sale con código 1
si algo falla; cada fallo trae el comando que lo arregla. También está en el dashboard
(super_admin → tenant → **Diagnóstico**).

```bash
python -m scripts.doctor --tenant <slug>
```

Con el doctor en verde, lo que solo se ve con tráfico real:

- [ ] `POST /v1/webhooks/test` desde Zernio → 200 en los logs de Cloud Run.
- [ ] Mensaje de prueba desde un móvil → fila en `inbound_jobs` → respuesta en WhatsApp.
- [ ] Trace en LangSmith con `channel=whatsapp` y el teléfono enmascarado.
- [ ] Escalado → ticket en Zendesk con transcripción, motivo y ventana (tags
      `auyan_handoff`, `auyan_whatsapp`); la IA calla mientras el ticket está abierto.
- [ ] Respuesta pública del agente en Zendesk → llega al WhatsApp del comprador.
- [ ] Ticket `solved` → la IA vuelve a atender.
- [ ] Plantilla de re-enganche **aprobada** en Meta.

## Staging: sandbox compartido

```bash
python -m scripts.onboard_whatsapp sandbox --tenant <slug> --staging --phone "+34…"
# después, responder en el móvil al WhatsApp del sandbox para activar la sesión (7 días)
```

El `accountId` del número compartido se lee de `GET /v1/phone-numbers` → `sandbox` (o
`--account-id`). El webhook va **sin** filtro `accountIds`: el número es de Zernio, no del
equipo, y Zernio responde `404 account_not_found`. El comando es idempotente (guarda
`sandbox_phone` para no reenviar la activación) y se niega si el tenant ya tiene un profile real.

**Del sandbox al número real:** primero `offboard` (borra la key y el webhook del sandbox) y
después `prepare`. `prepare` se niega si el tenant tiene el sandbox registrado: reutilizaría su
key de alcance completo y su webhook sin filtro.

El sandbox no tiene profile: el routing va por `account_id` y el índice único garantiza que
solo un tenant de staging lo tenga. **Excepción solo de staging:** la key del sandbox es de
alcance completo y caduca a los 30 días (una key limitada por profile no ve el sandbox).

## Baja

```bash
python -m scripts.onboard_whatsapp offboard --tenant <slug>
```

Borra el webhook y la key en Zernio y hace soft delete de la integración. El profile se
conserva (historial). Es repetible: borra primero en Zernio (también key/webhook huérfanos
por nombre) y al final hace el soft delete; lo que ya no existe sale como `skipped`.
