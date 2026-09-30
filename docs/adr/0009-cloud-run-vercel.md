# ADR 0009 — API en Google Cloud Run y dashboard en Vercel (sustituye a Railway)

**Estado:** Aceptada
**Fecha:** 2026-09-30 (migración en la sesión 77; dimensionado en la sesión 78)

## Contexto

Staging corría en Railway (API + dashboard). En la sesión 77 Railway se quedó sin
crédito en mitad del E2E de Zendesk y había que decidir dónde desplegar de forma
estable antes del piloto. Condiciones:

- La base de datos es Supabase en `eu-central-1` (Frankfurt), a través del pooler.
  Cada turno del agente hace decenas de queries, así que la latencia entre API y
  base de datos importa.
- Hasta tener un cliente de pago, el coste fijo tiene que ser ~0.
- La API necesita **CPU fuera del request**: el worker de la cola inbound
  ([ADR 0008](0008-inbound-queue-postgres.md)), el loop de cleanup y el listener
  `NOTIFY` de AOPs corren en segundo plano.
- Los secretos (claves de LLM, credenciales de integraciones cifradas, DSN) no
  pueden vivir en texto plano en la plataforma.

## Decisión

**API en Google Cloud Run y dashboard (`apps/web`) en Vercel.**

- Cloud Run `auyan-api-staging` en **`europe-west3` (Frankfurt)**, la misma zona que
  el pooler de Supabase. Proyecto `auyan-510116`. Deploy desde el código fuente con
  `apps/api/scripts/deploy_cloud_run.sh [ENV_FILE]`:
  - Las variables sensibles van a **Secret Manager**, una versión por cambio. Las
    anteriores se destruyen para no pagar por versiones.
  - Se usa una **service account dedicada** que solo lee sus propios secretos.
- **`--no-cpu-throttling`** (facturación por instancia): la CPU sigue asignada entre
  requests para el worker y los jobs de fondo. Con este modo el mínimo es **1 vCPU**;
  las fracciones exigen facturación por request y concurrencia 1.
- **`min-instances` configurable, 0 por defecto**
  (`CLOUD_RUN_MIN_INSTANCES` en el `.env` del entorno):
  - **Staging y producción arrancan con `min=0`** hasta firmar un cliente de pago.
    Coste ~0. A cambio, la instancia se apaga sin tráfico.
  - **Con el primer cliente de pago, producción pasa a `min=1`**: sin arranque en
    frío, y el worker procesa la cola continuamente. Precio oficial en
    `europe-west3`: $0.0000216/vCPU-s + $0.0000024/GiB-s ≈ **63 USD/mes** por una
    instancia de 1 vCPU y 1 GiB siempre encendida.
- **`max-instances=1`** en el piloto. La cola ya admite varias instancias (claim con
  lock por conversación), pero cada instancia abre su propio pool de conexiones.
- **Startup CPU Boost** activado, y **bytecode precompilado en la imagen**
  (`compileall` en el `Dockerfile`; Poetry no genera los `.pyc`). El arranque del
  contenedor bajó de **~15 s a ~10,7 s** (medido en los arranques por deploy).
- Vercel `auyan-web-staging` (raíz `apps/web`, pnpm). Supabase Auth apunta a Vercel.
- Railway NO aplicaba SQL y Cloud Run tampoco: las migraciones siguen
  aplicándose a mano (psql / Supabase SQL Editor).

## Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| **Seguir en Railway** | Se quedó sin crédito en mitad del E2E. La región no estaba junto a Supabase. El presupuesto no escalaba a cero con una API que necesita CPU en segundo plano. |
| **Fly.io / Render** | Válidas. Cloud Run ganó por Secret Manager integrado, escalado a cero con coste real cero, región en Frankfurt y el mismo proveedor que Cloud Tasks o Scheduler si luego hacen falta. |
| **Cloud Run con facturación por request (CPU solo durante el request)** | Más barato y admite fracciones de vCPU, pero el worker de la cola y el cleanup se quedarían sin CPU entre requests. |
| **Mantener caliente con un ping periódico** | Con facturación por instancia cuesta lo mismo que `min=1` y es más frágil. |
| **`min=1` solo en horario laboral** (~30 USD/mes) | Los clientes de e-commerce escriben de noche, y el primer mensaje de la mañana volvería a tener arranque en frío. |
| **API también en Vercel (Functions)** | La API es FastAPI con un worker en proceso, jobs de fondo y un listener `NOTIFY` de larga duración. Encaja con un contenedor, no con funciones. |

## Consecuencias

**Positivas:**
- Coste ~0 mientras no haya clientes. Se pasa a `min=1` cambiando una variable, sin
  tocar código.
- La API corre en la misma región que la base de datos. Los secretos están fuera
  del repo y fuera de la configuración en texto plano.
- Los logs quedan en Cloud Logging (`gcloud logging read`), con severidad, lo que
  permite alertas por logs.

**Negativas / costos asumidos:**
- **Con `min=0` hay arranque en frío de ~11 s.** Zendesk corta a ~10–12 s, así que
  el primer mensaje tras un rato de inactividad puede provocar un reintento. No se
  pierde nada (la idempotencia lo deduplica), pero cuenta como fallo del webhook en
  Zendesk. Además, los jobs de una instancia apagada esperan a la siguiente
  petición. Por eso **`min=1` es requisito operativo desde el primer cliente de
  pago**.
- Hay dos plataformas que operar (GCP + Vercel) en lugar de una.
- El despliegue de producción (`auyan-api` + Vercel prod) todavía no existe: se
  crea con el mismo script y otro `ENV_FILE`.
