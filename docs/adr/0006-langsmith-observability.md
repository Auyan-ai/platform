# ADR 0006 — LangSmith como fuente primaria de observabilidad

**Estado:** Aceptada
**Fecha:** 2026-06 (reencuadre 0.11A)

## Contexto

La observabilidad es el requisito más importante del proyecto: **todo lo que hace
el agente debe quedar trazado, sin excepción**. Cada conversación necesita una
traza completa (qué pensó, qué nodo del grafo corrió, qué skill llamó, por qué
decidió escalar, coste y errores), y cada run debe correlacionar con Supabase
(conversación, audit log). El proyecto ya tenía Langfuse conectado, pero la
verificación del agente en staging y los evals necesitaban una fuente única y
confiable, bien integrada con el grafo y el harness de evals.

## Decisión

**LangSmith es la fuente primaria de observabilidad en staging y evals. Langfuse
queda como espejo secundario mientras siga conectado, no como fuente de verdad
operativa.**

- Todo run del grafo se traza en LangSmith: nodos, child runs por nodo, llamadas
  al LLM, skills, coste y errores.
- Cada run en LangSmith correlaciona con Supabase (conversación, audit log, run).
- Los errores se capturan, loguean y alertan — nunca se silencian.
- En producción se requiere redacción/retención formal de PII antes de activar el
  trazado completo; en staging se trazan datos de test/autorizados.

## Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| **Mantener Langfuse como fuente primaria** | Ya estaba conectado, pero la integración con LangGraph y el harness de evals/simulator era menos directa para el flujo de trabajo de staging/evals. Se degrada a espejo en vez de arrancar de cero. |
| **Logging propio (structured logs + dashboard custom)** | Reinventar trazado de LLMs, árboles de runs, costos y evals. Meses de trabajo para igualar lo que LangSmith da listo. |
| **Sin observabilidad dedicada de LLM** | Violación directa del requisito no negociable del negocio. Descartado de entrada. |

## Consecuencias

**Positivas:**
- Integración nativa con LangGraph: los child runs por nodo aparecen sin
  instrumentación manual extra.
- Una sola fuente de verdad para staging/evals reduce ambigüedad operativa.
- El harness de evals y el simulator se apoyan en la misma plataforma.

**Negativas / costos asumidos:**
- Dependencia de un proveedor externo (lock-in parcial); se mitiga manteniendo
  la correlación con Supabase como registro propio.
- Convivencia temporal de dos sistemas (LangSmith + espejo Langfuse) hasta
  desconectar el segundo: doble destino de trazas mientras dure.
- Producción exige resolver redacción/retención de PII antes de trazar completo.
