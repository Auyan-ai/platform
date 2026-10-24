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
| [0008](0008-inbound-queue-postgres.md) | Turnos inbound en una cola Postgres, serializados por conversación | Aceptada |
| [0009](0009-cloud-run-vercel.md) | API en Cloud Run y dashboard en Vercel (sustituye a Railway); `min-instances` activable con el primer cliente de pago | Aceptada |
| [0010](0010-whatsapp-zernio-handoff.md) | WhatsApp vía Zernio como canal desacoplado del helpdesk, con handoff modular al helpdesk del cliente | Propuesta |
| [0011](0011-transcripcion-notas-de-voz.md) | Transcripción de notas de voz de WhatsApp detrás de `Transcriber` | Propuesta |
| [0012](0012-escritura-natural-por-canal.md) | Escritura natural por canal: el código pone el formato y la firma, el LLM la redacción | Propuesta |
| [0013](0013-verificacion-identidad-por-niveles.md) | Verificación de identidad en dos niveles (`guest` con número de pedido + contacto, `verified` por remitente, sesión firmada u OTP) decidida en código, con gate único y OTP opcional | Propuesta |
| [0014](0014-devoluciones-y-cambios-politica-del-tenant.md) | Devoluciones y cambios: política del tenant, decidida en código y sin valores por defecto | Propuesta |
| [0015](0015-url-a-agente.md) | De la URL de la tienda al agente: un motor de ingesta de fuentes oficiales para demos y onboarding, con citas verificadas en código | Propuesta |

## Estados posibles

- **Propuesta** — en discusión, aún no implementada.
- **Aceptada** — decisión vigente, reflejada en el código.
- **Superseded por [NNNN]** — reemplazada por una decisión posterior.
- **Deprecada** — ya no aplica, sin reemplazo directo.
