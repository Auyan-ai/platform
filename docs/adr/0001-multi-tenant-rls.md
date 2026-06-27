# ADR 0001 — Multi-tenancy con `tenant_id` + Row Level Security

**Estado:** Aceptada
**Fecha:** 2026-05 (fundacional)

## Contexto

Auyan opera el agente de IA de varios clientes (tenants) sobre una misma
plataforma. Cada tenant tiene su propia knowledge base (RAG), sus AOPs, sus
credenciales de integración y sus conversaciones. El requisito no negociable es:
**los datos de un cliente nunca pueden filtrarse a otro**. Una sola fuga
cross-tenant en un negocio que maneja datos de soporte (PII de clientes finales)
es un evento de extinción comercial y legal (GDPR: Auyan es encargado de
tratamiento).

Había que decidir el modelo de aislamiento antes de escribir la primera tabla,
porque cambiarlo después es una migración de datos completa.

## Decisión

**Una sola base de datos Postgres (Supabase) con `tenant_id` obligatorio en
todas las tablas y Row Level Security (RLS) activado en todas ellas.**

- Cada tabla operacional lleva `tenant_id` como columna obligatoria.
- RLS filtra cada query por el `tenant_id` del contexto de sesión (GUC
  `tenant_scope`), de modo que el aislamiento se impone **en la base de datos**,
  no solo en el código de la aplicación.
- El rol `super_admin` (Kenny + esposa) es la única excepción cross-tenant, y
  sus accesos quedan auditados.

## Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| **Una base de datos por tenant** | Aislamiento perfecto, pero operacionalmente insostenible para un equipo de 2: N migraciones, N backups, N conexiones. Provisionar un cliente nuevo dejaría de ser instantáneo. Sobreingeniería para el volumen objetivo (25-30 clientes año 1). |
| **Un schema de Postgres por tenant** | Punto medio, pero sigue multiplicando el costo de migraciones y rompe queries cross-tenant que el dashboard `super_admin` necesita (review queue, cola de reportes). |
| **Aislamiento solo en el código (sin RLS)** | Un solo `WHERE tenant_id` olvidado = fuga. Pone toda la seguridad en la disciplina del desarrollador. Inaceptable para el requisito. |

## Consecuencias

**Positivas:**
- El aislamiento vive en la capa de datos: aunque un endpoint tenga un bug,
  RLS sigue filtrando. Defensa en profundidad.
- Provisionar un tenant nuevo es insertar filas, no levantar infraestructura.
- El dashboard `super_admin` puede hacer queries cross-tenant legítimas sin
  conectarse a N bases.

**Negativas / costos asumidos:**
- Hay que pasar `tenant_scope` correctamente en cada conexión; un fallo en setear
  el GUC degrada a "sin acceso", no a "acceso a todo" — falla en seguro, pero
  hay que manejarlo.
- Las FKs compuestas `(user_id, tenant_id)` bloquean a `super_admin` cross-tenant;
  se decidió usar FK simple a `users(id)` y validar el tenant en la capa de
  servicio (ver código de servicios).
- Un tenant muy grande podría afectar el rendimiento de otros (vecino ruidoso);
  aceptable al volumen actual, a revisar si llega mid-market upper.
