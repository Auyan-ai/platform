# ADR 0005 — Skills tipadas con niveles de riesgo L1/L2/L3 y approval humano

**Estado:** Aceptada
**Fecha:** 2026-05 (arquitectura del agente v2)

## Contexto

El agente no solo responde: ejecuta acciones reales contra el e-commerce del
cliente vía Shopify. Esas acciones tienen riesgos muy distintos. Consultar el
estado de un pedido (lectura) es inofensivo. Cancelar un pedido o emitir un
reembolso es **irreversible y financiero**. Tratar todas las acciones igual sería
temerario: un cliente nuevo no va a confiar en que una IA cancele pedidos sin
red de seguridad. Pero exigir aprobación humana para todo mataría el valor de la
automatización.

## Decisión

**Cada acción es una "skill": una clase tipada con I/O Pydantic, registrada en un
registry, versionada y audit-logged. Las skills se clasifican en tres niveles de
riesgo, cada uno con su política de activación, supervisión y approval.**

| Tier | Naturaleza | Activación | Threshold | Supervisor | Approval humano |
|---|---|---|---|---|---|
| **L1** | Read-only | Día 1, todos los tenants | 0.70 | No | No |
| **L2** | Escritura bajo riesgo (reversible) | Día 1, opt-in | 0.85 | Sonnet | No |
| **L3** | Escritura alto riesgo (financiero, irreversible) | Tras 2-4 semanas de operación estable, opt-in | 0.95 | Opus | **Sí, el primer mes** |

- La activación es **progresiva**: L1 desde el día 1, L3 solo tras semanas de
  operación estable y opt-in explícito en `tenant_tool_permissions`.
- Cada AOP declara qué skills puede usar (`allowed_skills`); el selector inyecta
  **solo** esas tools al LLM (reduce ~60% de tokens y elimina alucinaciones
  cross-domain).
- Toda ejecución de skill queda en audit log con idempotency key.

Implementadas: 11 skills de Shopify (5 L1, 2 L2, 4 L3).
Inspirado en Sierra Agent SDK (skills tipadas) y Decagon (tiered tool risk +
progressive activation).

## Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| **Tool calling libre sin niveles** | Trata cancelar un pedido igual que consultarlo. Inaceptable para acciones financieras irreversibles. |
| **Aprobación humana para toda acción de escritura** | Mata el valor de la automatización; el operador se vuelve cuello de botella. |
| **Skills como funciones sueltas sin tipado** | Sin I/O Pydantic ni registry no hay validación, ni audit log consistente, ni idempotency. Frágil. |

## Consecuencias

**Positivas:**
- Modelo de confianza gradual: el cliente ve al agente operar en lectura, gana
  confianza, y solo entonces se activan acciones destructivas — con approval.
- El threshold creciente (0.70 → 0.95) y el supervisor por tier (Sonnet/Opus)
  escalan el rigor con el riesgo.
- Scopear las tools por AOP reduce tokens y alucinaciones.
- El audit log + idempotency hacen las acciones financieras seguras de reintentar.

**Negativas / costos asumidos:**
- Más infraestructura: registry, base class, permission gate, audit tables,
  cola de approvals con UI.
- La activación progresiva alarga el time-to-value de las acciones L3 (semanas),
  decisión deliberada a favor de la confianza.
- El supervisor (segundo modelo) añade latencia y costo a cada acción de
  escritura (ver [ADR 0007](0007-model-routing.md)).
