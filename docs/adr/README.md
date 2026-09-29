# Architecture Decision Records (ADRs)

Registro de las decisiones de arquitectura de Auyan. Cada ADR documenta **una**
decisión: el contexto en que se tomó, las alternativas consideradas, lo que se
decidió y las consecuencias (buenas y malas).

Formato basado en el modelo de [Michael Nygard](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).
Los ADRs son **inmutables**: si una decisión se revierte, no se borra — se crea
un ADR nuevo que la supersede y se actualiza el `Estado` del viejo.

## Índice

| # | Decisión | Estado |
|---|----------|--------|
| [0001](0001-multi-tenant-rls.md) | Multi-tenancy con `tenant_id` + Row Level Security (una sola base de datos) | Aceptada |
| 0002 | _Retirado: era una decisión de negocio, no de arquitectura_ | — |
| [0003](0003-langgraph-agent.md) | Agente como grafo de estados (LangGraph) en vez de prompt monolítico | Aceptada |
| [0004](0004-aops-runtime-editable.md) | Comportamiento del agente en AOPs editables en runtime (no en código) | Aceptada |
| [0005](0005-skills-tiered-l1-l2-l3.md) | Skills tipadas con niveles de riesgo L1/L2/L3 y approval humano | Aceptada |
| [0006](0006-langsmith-observability.md) | LangSmith como fuente primaria de observabilidad | Aceptada |
| [0007](0007-model-routing.md) | Routing de modelos por tarea (Haiku/Sonnet/Opus) según costo-profundidad | Aceptada |

## Estados posibles

- **Propuesta** — en discusión, aún no implementada.
- **Aceptada** — decisión vigente, reflejada en el código.
- **Superseded por [NNNN]** — reemplazada por una decisión posterior.
- **Deprecada** — ya no aplica, sin reemplazo directo.
