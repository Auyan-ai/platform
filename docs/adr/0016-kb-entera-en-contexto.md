# ADR 0016 — La KB entera en el prompt cuando cabe, RAG cuando no

**Estado:** Aceptada
**Fecha:** 2026-10-25
**Relación:** issue #410; guía de Anthropic sobre Contextual Retrieval; [ADR 0015](0015-url-a-agente.md).

## Contexto

En staging el RAG no recuperaba nada en el 96 % de los turnos (#410). Con el umbral quitado
y la consulta hecha con la conversación llega a 12/12 en el experimento de Thinking MU, pero
sigue siendo un punto de fallo por turno: embeddings, umbral, `top_k`, troceo. La KB de una
tienda son 10-20k tokens. Anthropic recomienda meter la KB entera en el prompt, con prompt
caching, por debajo de ~200k tokens.

## Decisión

Cada turno se resuelve en uno de dos modos (`KnowledgeMode`, `services/knowledge_mode.py`):

- `full_context`: la KB viva del tenant entra entera en el system. `retrieve_knowledge` no
  embebe ni busca.
- `retrieval`: el RAG de siempre (top-k sin umbral, consulta con los últimos mensajes).

`choose_knowledge_mode(total_tokens, budget)` es una función pura. Los tokens se estiman en
código, por exceso (`ceil(caracteres / 3.5)`), sin llamar a ningún modelo. El presupuesto es
`kb_full_context_token_budget`: 50.000 por defecto (muy por debajo de los 200k de Anthropic, a
propósito, para proteger la atención y el coste), y se puede cambiar por tenant en
`tenant_configurations.extra`.

`load_tenant_context` decide el modo con una sola consulta (documentos vivos ordenados por
título e id; el contenido solo viaja si la KB cabe). El modo queda en `state["knowledge"]` y
lo leen `retrieve_knowledge`, `reason` y `supervise`.

### Orden de los bloques del system

1. KB entera (`cache_control`), solo en `full_context`.
2. AOP compilado (`cache_control`).
3. Bloque volátil del turno, sin cachear.

La KB va antes que el AOP porque cambia solo cuando el tenant la edita, mientras que el AOP
cambia con la intención. Con las tools suman 3 de los 4 breakpoints. Las tools preceden al
system en el prefijo de Anthropic, así que dos AOPs comparten la caché de la KB solo si
exponen las mismas tools.

El supervisor recibe los mismos bloques estables como evidencia (no rechaza como inventado lo
que el agente leyó en la KB) y el juez del simulador ve los documentos en vez de chunks.

## Consecuencias

- Una KB de tienda deja de depender del RAG. Las que superan el presupuesto siguen por RAG.
- Editar la KB invalida la caché del tenant una vez.
- Cada turno registra modo, tokens estimados y nº de documentos en el evento de razonamiento y
  en LangSmith (`retrieval_summary`).
