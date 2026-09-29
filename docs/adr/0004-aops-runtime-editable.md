# ADR 0004 — Comportamiento del agente en AOPs editables en runtime

**Estado:** Aceptada
**Fecha:** 2026-05 (arquitectura del agente v2)

## Contexto

El equipo interno opera el agente de cada tenant y lo ajusta
**cada semana**. Si cada ajuste de comportamiento (cambiar
cuándo escala, afinar el tono, añadir una regla a las devoluciones) requiere un
PR + review + deploy, la velocidad de iteración muere y la promesa comercial no
se sostiene. Además distintos tenants necesitan comportamientos distintos para el
mismo intent. La velocidad de iteración es prioridad explícita del proyecto.

## Decisión

**El comportamiento del agente vive en AOPs (Agent Operating Procedures):
documentos en lenguaje natural (YAML frontmatter + cuerpo en Markdown) guardados
en la base de datos y editables en runtime desde el dashboard interno, sin
redeploy.**

- Cada AOP define cuándo se activa, qué skills puede usar (`allowed_skills`),
  reglas deterministas que el supervisor verifica, y cuándo escalar.
- El system prompt del agente se **compila en runtime** a partir del AOP activo.
- Versionado **append-only**: cada guardado es una fila nueva en `aop_versions`
  (inmutable, auditable).
- **Workspaces** `staging` / `production`: se itera en staging, se promueve a
  production solo tras pasar el eval gate (umbral 80%).
- Cache con TTL de 60s por `(tenant_id, slug, workspace)` + invalidación vía
  Postgres NOTIFY.

Inspirado en Decagon AOPs y Sierra `SKILL.md`.

## Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| **Comportamiento hardcoded en código** | Cada tweak = PR + deploy. Mata la velocidad de iteración y la promesa de "mejora semanal". No escala a comportamiento por-tenant. |
| **Config en JSON/YAML en el repo** | Sigue requiriendo deploy. No permite que el operador edite desde el dashboard ni versiona por tenant en DB. |
| **Fine-tuning por tenant** | Lento, caro, opaco. Imposible de iterar semanalmente o auditar qué cambió y por qué. |

## Consecuencias

**Positivas:**
- El operador ajusta comportamiento en minutos desde el dashboard, no en un ciclo
  de deploy.
- El versionado append-only da trazabilidad total: qué cambió, cuándo, y se puede
  revertir.
- Los workspaces + eval gate evitan que un cambio rompa producción: nada se
  promueve sin pasar los evals.
- Habilita el flywheel del slow agent: el job nocturno propone diffs al AOP que
  un humano aprueba.

**Negativas / costos asumidos:**
- Comportamiento en lenguaje natural = menos determinista que código. Se mitiga
  con reglas deterministas que el supervisor verifica explícitamente
  (ver [ADR 0005](0005-skills-tiered-l1-l2-l3.md)).
- Hay que mantener infraestructura extra: compiler, cache con invalidación,
  tabla de versiones, eval gate.
- Editar el comportamiento del agente desde una UI es poderoso y peligroso: exige
  el gate de evals como red de seguridad obligatoria.
