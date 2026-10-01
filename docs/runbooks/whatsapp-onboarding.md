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
equipo, y Zernio responde `404 account_not_found`. El comando es idempotente.

El sandbox no tiene profile: el routing va por `account_id` y el índice único garantiza que
solo un tenant de staging lo tenga. **Excepción solo de staging:** la key del sandbox es de
alcance completo y caduca a los 30 días (una key limitada por profile no ve el sandbox).

## Baja

```bash
python -m scripts.onboard_whatsapp offboard --tenant <slug>
```

Borra el webhook y la key en Zernio y hace soft delete de la integración. El profile se
conserva (historial).
