# Mapa de verificación — Auyan

Fuente mantenida para verificar el comportamiento de cara al usuario. Léelo antes de conducir la app y usa el archivo de la feature como receta.

## Precondiciones base

- Entorno: **staging real** (Supabase `johidurhcobdkpvlnowl`, LLM real) con código local. Tenant `marea-studio` (id `683246c2-10ce-4f6c-a299-5053f32f8c01`). Ver `../SKILL.md`.
- `scripts/doctor.sh` sin `FAIL`; API local en `:8000` arrancada con `scripts/up.sh api` (worker de cola apagado).
- Para las features de dashboard: `scripts/up.sh web` y una sesión guardada por Kenny (`scripts/web-login.sh`) con `super-admin@auyan.ai` (rutas `/tenants/...`) y, para `/clients/...`, otra con `VERIFY_PROFILE=tenant` (`kennyrmv@gmail.com`, tenant_admin de Marea). **La web necesita la API local arriba.** Sin sesión, esas features **no son verificables**: repórtalo, no las des por probadas por otra vía.
- Nunca conduzcas una instancia que no arrancó esta corrida.

## Convenciones

- Los comandos son literales; las rutas son relativas a la raíz del repo (`.claude/skills/verify/scripts/...`).
- Dashboard: prefiere roles/nombres accesibles y los `h1` listados aquí sobre CSS o posición.
- Toda prueba guarda la acción **y** el estado resultante (respuesta HTTP cruda + `dump.sh` / captura) en `evidence/`.
- Cada artefacto se nombra con el ID de la feature (`agent-respond`, …) y el punto de entrada usado.
- Las pruebas crean datos en staging (cliente `VERIFY bot`). No borres nada sin OK de Kenny; si toca, soft delete.
- Un punto de entrada inalcanzable se reporta con el comando intentado y la precondición que falta.

## Features

| Feature | Estado en la última corrida |
|---|---|
| [Agente responde](./agent-respond.md) — webhook → grafo → respuesta con KB/skills L1 | ✅ probada (2026-10-11) |
| [Agente escala](./agent-escalate.md) — pide humano / queja grave → escalación con motivo | ✅ probada (2026-10-11) |
| [Inbox del dashboard](./inbox.md) — conversaciones, razonamiento, escalaciones | ✅ probada (2026-10-11, super_admin, rutas `/tenants/...`) |
| [Aprobaciones L3](./approvals-l3.md) — cola de aprobación y rechazo | ✅ pendiente + rechazo probados (2026-10-11); aprobar no se automatiza |
| [Conocimiento y hechos](./knowledge-facts.md) — KB y `tenant_facts` del cliente | ✅ lectura y escritura probadas (2026-10-11): hecho editado/restaurado y KB enviada → aprobada → en la respuesta → retirada |
| [Vista del cliente](./client-views.md) — overview, conversaciones, escalaciones, aprobaciones, insights, reportes y configuración | ✅ probada (2026-10-11, tenant_admin) |
