# ADR 0007 — Routing de modelos por tarea (Haiku/Sonnet/Opus)

**Estado:** Aceptada
**Fecha:** 2026-05 (arquitectura del agente v2)

## Contexto

El agente hace tareas con exigencias muy distintas dentro de un mismo flujo:
clasificar un intent (rápido, alto volumen, bajo riesgo), razonar la respuesta
(calidad importa), supervisar una acción financiera (máxima fiabilidad). Usar el
modelo más potente para todo es caro y lento; usar el más barato para todo
compromete las decisiones críticas. El costo de LLM es una línea directa del
margen del negocio, y la conciencia de costos es un valor explícito del proyecto.

## Decisión

**Cada tarea del grafo usa el modelo cuyo perfil costo/profundidad encaja con su
exigencia, no un modelo único para todo (Constellation of models, estilo Sierra).**

| Tarea | Modelo | Razón |
|---|---|---|
| Clasificador de intent (`select_aop`) | Haiku 4.5 | Alto volumen, baja complejidad, latencia importa. |
| User simulator (evals) | Haiku 4.5 | Genera turnos de usuario sintético en masa; barato. |
| Razonamiento principal (`reason`) | Sonnet 4.6 | Calidad de respuesta con costo razonable. Default. |
| Supervisor L1/L2 | Sonnet 4.6 | Valida escrituras de bajo riesgo. |
| Supervisor L3 / financiero | Opus | Máxima fiabilidad en acciones irreversibles. |
| Judge / calibración explícita | Opus | El juez del slow agent escala a Opus si la confianza del primer paso es baja. |

Nota de honestidad incluida en el diseño: **no esperamos el `90% × 90% → 99%`**
que vende el marketing del patrón Constellation — los errores correlacionan
(mismo contexto, modelos parecidos). Se apunta a 40-60% de reducción de errores
de escritura, **a medir con `supervisor_override_rate` real**.

## Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| **Un solo modelo potente (Opus) para todo** | Caro y lento para tareas de alto volumen como la clasificación de intent. Destruye el margen. |
| **Un solo modelo barato (Haiku) para todo** | Compromete el razonamiento y, sobre todo, la supervisión de acciones financieras. Riesgo inaceptable donde importa. |
| **Embeddings para el routing de intent** (en vez de Haiku) | Más barato y rápido, pero la clasificación de intent en CX depende del contexto conversacional, no solo de similitud semántica. Queda como pre-filtro futuro, no como reemplazo. |

## Consecuencias

**Positivas:**
- Costo optimizado: se paga por capacidad donde hace falta, no en todas partes.
- El rigor escala con el riesgo (Opus solo donde el error es irreversible).
- Decisiones de modelo explícitas y medibles (`supervisor_override_rate`), no
  por intuición.

**Negativas / costos asumidos:**
- Más complejidad: hay que configurar y mantener qué modelo usa cada tarea.
- Acoplamiento a una familia de modelos concreta; cambiar de proveedor obliga a
  re-mapear cada tarea.
- El patrón Constellation añade latencia y costo en cada escritura supervisada;
  se justifica solo donde el riesgo lo amerita, no en lectura.
