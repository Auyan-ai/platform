# Auyan — Construyendo un Managed AI Service para soporte de e-commerce

> **TL;DR** — Diseñé y construí desde cero la plataforma de un servicio gestionado
> de IA para soporte al cliente de e-commerce español: un agente que entiende
> tickets, ejecuta acciones reales contra Shopify (consultar pedidos, cancelar,
> reembolsar) bajo aprobación humana, y mejora cada semana. Arquitectura
> multi-tenant con aislamiento a nivel de base de datos, agente construido como
> grafo de estados en LangGraph, comportamiento editable en caliente sin redeploy,
> y observabilidad total de cada decisión. Stack: FastAPI · Next.js · Supabase ·
> LangGraph · Claude · LangSmith.

---

## El problema

El soporte al cliente en e-commerce es 60-80% trabajo repetitivo: leer el ticket,
buscar el pedido, responder lo de siempre, ejecutar la acción rutinaria (devolución,
cambio de dirección, cancelación). Las tiendas españolas medianas tienen equipos
de CX que se ahogan en ese volumen, pero las soluciones disponibles las dejan
solas: o contratan un BPO (caro, no escala) o compran un SaaS de chatbot que
tienen que configurar y mantener ellas mismas (y que nunca pasa del 50% de
resolución porque nadie lo optimiza).

Hay un hueco: un servicio que **opere** el agente de IA por ellas, no que se lo
venda como herramienta.

## La decisión de producto que condicionó todo lo técnico

Antes de escribir una línea de código, la decisión más importante fue **qué
vender**. Lo resolví así: Auyan es un **Managed AI Service**. Configuramos,
mantenemos y optimizamos el agente del cliente; el cliente conserva su equipo
humano para los escalados. No somos un BPO (no atendemos tickets) ni un SaaS
self-serve (el cliente no configura nada). El entregable diferenciador es un
**reporte semanal proactivo** con mejoras concretas que el cliente aprueba.

Esta decisión tiene una consecuencia técnica directa: **la complejidad vive de
nuestro lado**. Construí dos superficies — un control plane interno potente
(editor de comportamiento, simulador, aprobaciones, auditoría) y una experiencia
de cliente deliberadamente simple. El margen de contribución del modelo es ~79%.

> Decisión documentada en detalle: [ADR 0002](adr/0002-managed-ai-service-model.md).

## Las decisiones de arquitectura que más importan

### 1. Multi-tenant con aislamiento en la base de datos, no en el código

Una sola fuga de datos entre clientes es un evento de extinción (legal y
comercial). En vez de confiar el aislamiento a que ningún desarrollador olvide
un `WHERE tenant_id`, lo puse **en la base de datos** con Row Level Security:
aunque un endpoint tenga un bug, Postgres sigue filtrando por tenant. Defensa en
profundidad. Descarté "una base de datos por cliente" porque un equipo de 2 no
puede operar N bases — provisionar un cliente nuevo es insertar filas, no levantar
infraestructura. → [ADR 0001](adr/0001-multi-tenant-rls.md)

### 2. El agente es un grafo de estados, no un prompt gigante

El agente clasifica el intent, recupera contexto, razona, ejecuta acciones reales,
las valida con un segundo modelo y decide si escala — todo trazado. Meter eso en
un solo prompt es imposible de testear y depurar. Lo construí como un **grafo de
11 nodos en LangGraph** con dos loops controlados (ReAct para acción-observación,
y supervisión para validar escrituras), cada uno con límites duros para evitar
loops infinitos y costos descontrolados. Cada nodo se testea aislado y cada
transición queda en la traza. → [ADR 0003](adr/0003-langgraph-agent.md)

### 3. El comportamiento del agente se edita en caliente, sin redeploy

El modelo de negocio promete mejorar el agente **cada semana**. Si cada ajuste
fuera un PR + deploy, esa promesa no se sostiene. Saqué el comportamiento del
código y lo puse en **AOPs** (Agent Operating Procedures): documentos en lenguaje
natural, guardados en base de datos, versionados (append-only) y editables desde
el dashboard. Se itera en un workspace de staging y solo se promueve a producción
tras pasar un gate de evals automático (umbral 80%). El operador afina el agente
en minutos, no en un ciclo de deploy. → [ADR 0004](adr/0004-aops-runtime-editable.md)

### 4. Acciones con niveles de riesgo y aprobación humana donde duele

El agente no solo responde: cancela pedidos y emite reembolsos. Tratar "consultar
un pedido" igual que "reembolsar 200€" sería temerario. Clasifiqué cada acción
("skill") en tres niveles: **L1** lectura (día 1), **L2** escritura reversible
(supervisada por un modelo), **L3** financiera irreversible (umbral de confianza
0.95, supervisada por el modelo más potente, y **con aprobación humana el primer
mes**). La activación es progresiva: el cliente ve al agente operar en lectura,
gana confianza, y solo entonces se activan las acciones destructivas. → [ADR 0005](adr/0005-skills-tiered-l1-l2-l3.md)

### 5. Cada euro de IA se gasta donde hace falta

El costo de los modelos es una línea directa del margen. En vez de usar el modelo
más potente para todo, cada tarea usa el que encaja: un modelo rápido y barato
para clasificar intents (alto volumen), uno equilibrado para razonar, y el más
potente solo para supervisar acciones financieras irreversibles. Decisiones de
modelo explícitas y **medibles**, no por intuición. → [ADR 0007](adr/0007-model-routing.md)

### 6. Observabilidad total: nada que el agente haga es invisible

Requisito no negociable: cada conversación tiene una traza completa — qué pensó
el agente, qué nodo corrió, qué acción llamó, por qué escaló, cuánto costó.
Centralicé la observabilidad en LangSmith, correlacionada con la base de datos
propia, y con una regla férrea: los errores se capturan, loguean y alertan,
nunca se silencian. → [ADR 0006](adr/0006-langsmith-observability.md)

## El resultado

- Agente conversacional en producción capaz de **resolver y ejecutar acciones
  reales** de soporte de e-commerce, no solo responder con FAQs.
- **11 integraciones de acción con Shopify** (lectura, escritura reversible y
  acciones financieras con aprobación).
- Comportamiento **iterable en caliente** por cliente, con gate de evals que
  protege producción.
- **Flywheel de conocimiento**: cada escalado que el equipo humano resuelve
  alimenta un job nocturno que propone mejoras al comportamiento del agente — la
  resolución automática sube sola con el tiempo.
- Plataforma multi-tenant con aislamiento a nivel de base de datos, auditoría
  GDPR-ready y observabilidad de cada decisión.

## Lo que demuestra este proyecto

No es un demo de chatbot. Es un sistema de producción donde cada decisión de
arquitectura traza directamente a una restricción real del negocio: aislamiento
por requisito legal, comportamiento editable por la promesa comercial, niveles de
riesgo por la confianza del cliente, routing de modelos por el margen. Diseñar
agentes de IA que ejecutan acciones con dinero real exige pensar en seguridad,
reversibilidad, observabilidad y costo desde el día 1 — y eso es exactamente lo
que documenté en los [ADRs](adr/README.md).

---

*Stack: FastAPI (Python 3.12) · Next.js 15 + TypeScript · Supabase (Postgres +
pgvector + RLS) · LangGraph · Claude (Haiku/Sonnet/Opus) · LangSmith · Railway.*
