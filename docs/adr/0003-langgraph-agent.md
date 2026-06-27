# ADR 0003 — Agente como grafo de estados (LangGraph)

**Estado:** Aceptada
**Fecha:** 2026-05 (arquitectura del agente v2)

## Contexto

El agente tiene que hacer mucho más que "responder con RAG": clasificar el intent
del ticket, recuperar contexto del tenant, ejecutar acciones reales (consultar
Shopify, cancelar un pedido), validar esas acciones antes de ejecutarlas, decidir
si escala a un humano, y dejar **todo** trazado. Hacer esto en un solo prompt
gigante con la lógica embebida en strings es imposible de testear, depurar y
observar — y la observabilidad es requisito no negociable del negocio (cada
decisión del agente debe ser auditable).

## Decisión

**El agente es un grafo de estados explícito en LangGraph, con 11 nodos y dos
loops controlados.**

Nodos principales: `load_tenant_context` → `load_conversation` → `select_aop`
→ `retrieve_knowledge` → `reason` ⇄ `execute_skill` / `supervise` →
`respond` / `escalate` / `handle_error` → `finalize_trace`.

Dos loops con límites duros:
- **Loop ReAct** (`reason ⇄ execute_skill`): el agente razona, decide si necesita
  una skill, la ejecuta, vuelve a razonar. Límite: `max_tool_iterations = 5`
  (configurable por AOP).
- **Loop de supervisión** (`reason → supervise`): para acciones de escritura un
  segundo modelo valida el reasoning. Si rechaza, una reintentada; si vuelve a
  fallar, escala.

Cada nodo es un archivo aislado, testeable por separado, y cada transición queda
registrada en LangSmith.

## Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| **Prompt monolítico** (toda la lógica en un system prompt + tool calling libre) | Imposible de testear nodo por nodo. La lógica de negocio (cuándo escalar, qué validar) queda atrapada en lenguaje natural sin estructura. Depurar un fallo = leer un transcript de 4000 tokens. |
| **Cadena lineal sin loops** (estilo pipeline) | No soporta el patrón ReAct (razonar → actuar → observar → re-razonar) que las acciones reales necesitan. |
| **Framework de agentes "todo incluido"** (AutoGPT-like) | Demasiada magia, poco control sobre las transiciones. El negocio exige control determinista sobre cuándo se llama a un humano y cuándo se ejecuta una acción financiera. |

## Consecuencias

**Positivas:**
- Cada nodo se testea aislado; el grafo completo se prueba con el eval harness y
  el simulator multi-turno.
- La traza en LangSmith mapea 1:1 al grafo: se ve qué nodo corrió, en qué orden
  y por qué — exactamente lo que el negocio exige.
- Los límites duros (`max_tool_iterations`, una sola reintentada de supervisión)
  evitan loops infinitos y costos descontrolados.

**Negativas / costos asumidos:**
- Más boilerplate que un prompt suelto: definir state, nodos, edges condicionales.
- La curva de aprendizaje de LangGraph (state management, edges) es real.
- El grafo hay que mantenerlo en sync con los AOPs (ver [ADR 0004](0004-aops-runtime-editable.md)).
