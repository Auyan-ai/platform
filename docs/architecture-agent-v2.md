# Arquitectura del Agente — v2

_Diseño actualizado del agente conversacional para soportar acciones, AOPs (Agent Operating Procedures), supervisor pattern y mejora continua._

> **Estado 2026-05-28:** documento de arquitectura histórico-vivo. Muchas piezas ya están implementadas; el estado operativo vigente manda en `docs/progress.md`.
> 0.11A reencuadra la verificación del agente: LangSmith como observabilidad primaria de staging/evals, simulator con Sonnet judge por defecto, Shopify test store real y Chatwoot primero.

---

## 1. Resumen ejecutivo

El agente actual sabe **responder** o **escalar** usando RAG sobre la KB del tenant. No puede ejecutar acciones (consultar Shopify, cancelar pedido, etc.) y no tiene segundo modelo validando antes de enviar.

La v2 introduce cuatro cambios estructurales:

1. **Skills framework**: cada acción del agente (lectura o escritura) es una clase tipada con I/O Pydantic, registrada en un registry, versionada y audit-logged. Inspirado en Sierra Agent SDK.
2. **Agent Operating Procedures (AOPs)**: la lógica de cuándo y cómo el agente actúa vive en procedimientos en lenguaje natural editables en runtime desde el dashboard interno. Cada AOP define qué skills puede usar. Inspirado en Decagon AOPs y Sierra `SKILL.md`.
3. **Supervisor pattern (Constellation Lite)**: cuando el agente decide acciones de escritura, un segundo modelo evalúa el reasoning antes de ejecutar. Sonnet supervisa para L1/L2, Opus supervisa para L3 (acciones financieras). Inspirado en Sierra Constellation.
4. **Slow agent de mejora continua**: job nocturno que lee transcripciones, AOPs y código, y propone diffs concretos al AOP para que un humano apruebe. Inspirado en Decagon Duet.

El sistema se diseña desde el día 1 con **idempotency, audit log, feature flags por tenant y workspaces (prod/staging)** para iterar rápido sin romper producción.

---

## 2. Inspiración tomada de la industria

| Concepto | Origen | Cómo lo aplicamos en Auyan |
|---|---|---|
| `SKILL.md` con YAML frontmatter | Sierra Agent SDK | Schema de AOPs: frontmatter estructurado + cuerpo en lenguaje natural |
| Tools scopeadas por skill/playbook | Sierra | Cada AOP declara `allowed_skills`. El selector inyecta solo esas tools al LLM. Reduce ~60% tokens y elimina cross-domain hallucinations |
| Deterministic guardrails | Sierra | Keywords/reglas en el AOP que el supervisor verifica explícitamente (no confía en el LLM) |
| Natural language editable en runtime | Decagon AOPs | Body del AOP en markdown, editable desde dashboard sin redeploy |
| Versionado append-only de procedimientos | Decagon Agent Versioning | Tabla `aop_versions` inmutable, cada save = nueva fila |
| Workspaces (prod/staging) | Decagon | Cada AOP tiene workspace; el grafo carga según `workspace=production` por defecto |
| Constellation of models | Sierra | Modelo principal (Sonnet) + supervisor (Sonnet/Opus según tier). **No esperamos el `90% × 90% → 99%` que vende el marketing**: errores correlacionan (mismo contexto, modelos parecidos). Apuntamos a 40-60% de reducción de errores de write — a medir con `supervisor_override_rate` real |
| Tiered tool risk + progressive activation | Decagon | L1 read día 1, L2 write bajo riesgo día 1, L3 alto riesgo solo tras 2-4 semanas de operación estable |
| Slow agent / Duet | Decagon | Job nocturno LLM-as-judge que propone diffs al AOP |

**Referencias:**
- [Sierra Constellation of models](https://sierra.ai/blog/constellation-of-models)
- [Sierra Agent SDK](https://sierra.ai/product/develop-your-agent)
- [Decagon AOPs](https://decagon.ai/product/aop)
- [Decagon Agent Versioning](https://decagon.ai/resources/decagon-agent-versioning)
- [Decagon: from SOPs to AOPs](https://decagon.ai/resources/from-sops-to-agent-operating-procedures)

---

## 3. Arquitectura del grafo

### 3.1 Diagrama

```
                        START
                          │
                          ▼
              ┌──────────────────────────┐
              │   load_tenant_context    │
              └──────────────────────────┘
                          │
                          ▼
              ┌──────────────────────────┐
              │    load_conversation     │
              └──────────────────────────┘
                          │
                          ▼
              ┌──────────────────────────┐
              │  select_aop  (NUEVO)     │   ← clasifica intent → AOP slug
              └──────────────────────────┘
                          │
                          ▼
              ┌──────────────────────────┐
              │   retrieve_knowledge     │   ← (opcional, según AOP)
              └──────────────────────────┘
                          │
                          ▼
              ┌──────────────────────────┐
              │   reason  (REWORKED)     │ ◄──┐
              └──────────────────────────┘    │
                          │                   │
              ┌───────────┴───────────┐       │
              ▼                       ▼       │
   ┌──────────────────┐   ┌────────────────────┐
   │  execute_skill   │   │     supervise      │
   │      (NUEVO)     │   │      (NUEVO)       │
   └──────────────────┘   └────────────────────┘
              │                       │
              └───────────────────────┤
                                      ▼
                  ┌───────────────────────────────┐
                  ▼               ▼               ▼
            ┌──────────┐   ┌──────────┐   ┌──────────────┐
            │ respond  │   │ escalate │   │ handle_error │
            └──────────┘   └──────────┘   └──────────────┘
                  │               │               │
                  └───────────────┼───────────────┘
                                  ▼
                       ┌────────────────────┐
                       │  finalize_trace    │
                       └────────────────────┘
                                  │
                                  ▼
                                 END
```

### 3.2 Nuevos nodos

| Nodo | Responsabilidad |
|---|---|
| `select_aop` | Clasifica intent con Haiku. Elige AOP slug + confidence. Si `confidence < umbral_intent`, usa AOP `default` (catch-all) |
| `execute_skill` | Recibe `tool_call` desde el state. Resuelve clase, valida idempotency, ejecuta, persiste audit log, devuelve resultado al state |
| `supervise` | Recibe la decisión propuesta por `reason`. Evalúa con segundo modelo (Sonnet o Opus según tier). Aprueba, rechaza con razón, o pide re-reason |

### 3.3 Loops del grafo

**Loop ReAct** (`reason ⇄ execute_skill`):
- `reason` decide si necesita tool. Si sí, emite `pending_tool_call`.
- `execute_skill` corre la skill, agrega `ToolResult` al state.
- Vuelve a `reason` para nueva iteración.
- Límite duro: `max_tool_iterations = 5` (configurable por AOP).

**Loop de supervisión** (`reason → supervise`):
- `supervise` solo se activa si la decisión incluye tools L2+ o si el AOP marca `require_supervision: true`.
- Si rechaza: vuelve a `reason` con feedback. Una sola reintentada. Si vuelve a fallar, escala.

### 3.4 Edges condicionales

```python
def route_after_reason(state):
    if state.get("error"): return "handle_error"
    if state.get("pending_tool_call"): return "execute_skill"
    if needs_supervision(state): return "supervise"
    if state["decision"] == "respond": return "respond"
    if state["decision"] == "escalate": return "escalate"
    return "handle_error"

def route_after_supervise(state):
    if state["supervisor_verdict"] == "approve":
        return state["decision"]  # respond | escalate
    # Reject: el supervisor distingue tactical vs structural
    if state["supervisor_reject_kind"] == "structural":
        return "escalate"  # AOP no aplica / falta capability → humano, sin reintento
    if state["supervisor_reject_kind"] == "tactical" and not state.get("supervisor_retried"):
        return "reason"  # falta verificar algo concreto → una reintentada
    return "escalate"  # tactical rechazado dos veces o falta info → humano

def route_after_execute_skill(state):
    if state.get("tool_iterations", 0) >= state["max_tool_iterations"]:
        return "escalate"  # loop infinito → humano
    return "reason"
```

---

## 4. State del grafo

Cambios al `AgentState` (`apps/api/agents/state.py`):

```python
class AgentState(TypedDict, total=False):
    # --- existentes (sin cambios) ---
    tenant_id: str
    conversation_id: str
    inbound_message_id: str
    inbound_message_content: str
    channel: str
    end_customer_id: str
    tenant_config: dict
    system_prompt: str  # ahora se compone con AOP, no es estático
    model_used: str
    conversation_history: list[dict]
    end_customer: dict
    retrieved_chunks: list[dict]
    decision: Decision
    confidence: float
    escalation_reason: str | None
    agent_response: str | None
    tokens_in: int
    tokens_out: int
    cost_usd: float
    output_message_id: str
    escalation_id: str
    langfuse_trace_id: str | None
    error: str | None

    # --- NUEVOS ---
    aop_slug: str                       # AOP seleccionado por select_aop
    aop_version: int                    # versión exacta cargada
    aop_workspace: str                  # production | staging
    intent_confidence: float            # confianza del selector

    allowed_skills: list[str]           # subset que define el AOP

    pending_tool_call: dict | None      # {name, input, idempotency_key}
    tool_results: list[dict]            # historial de tool_use + tool_result
    tool_iterations: int                # contador de loops
    max_tool_iterations: int            # default 5, override por AOP

    supervisor_verdict: Literal["approve", "reject"] | None
    supervisor_reason: str | None
    supervisor_reject_kind: Literal["tactical", "structural"] | None  # tactical=reintentable, structural=escalar
    supervisor_retried: bool
    supervisor_model_used: str | None
    supervisor_tokens_in: int
    supervisor_tokens_out: int

    # --- Intent (de select_aop) ---
    intent_alternatives: list[dict]     # top-2 candidatos {slug, confidence} para audit
    intent_ambiguity_detected: bool     # múltiples intents en el mismo mensaje
    aop_locked_until_turn: int | None   # si seteado, no reclasificar hasta llegar a este turno
    aop_completed_signal: bool          # el flujo del AOP terminó (cliente dijo "listo")
    pending_intent: str | None          # slug del segundo intent pendiente de atender (del alternative)
```

---

## 5. Skills framework

### 5.1 Clase base

```python
# apps/api/skills/base.py
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import ClassVar, Literal
from pydantic import BaseModel

SkillTier = Literal["L1", "L2", "L3"]

class SkillInput(BaseModel):
    pass

class SkillOutput(BaseModel):
    pass

class Skill(ABC):
    """Base class for all agent skills."""

    slug: ClassVar[str]                    # e.g. "shopify.get_order_by_email"
    description: ClassVar[str]             # what it does (shown to LLM)
    tier: ClassVar[SkillTier]              # L1 | L2 | L3
    input_schema: ClassVar[type[SkillInput]]
    output_schema: ClassVar[type[SkillOutput]]
    requires_idempotency: ClassVar[bool] = False  # True para todo L2/L3 write
    default_threshold: ClassVar[float]     # 0.70 / 0.85 / 0.95 según tier

    @abstractmethod
    async def execute(
        self,
        ctx: SkillContext,
        inputs: SkillInput,
    ) -> SkillOutput:
        """Execute the skill. Must be idempotent if requires_idempotency=True."""
        ...

    def to_anthropic_tool(self) -> dict:
        """Convert to Anthropic tool definition for Claude API."""
        return {
            "name": self.slug.replace(".", "_"),
            "description": self.description,
            "input_schema": self.input_schema.model_json_schema(),
        }
```

### 5.2 Registry

```python
# apps/api/skills/registry.py
class SkillRegistry:
    """Singleton. Discovers all Skill subclasses at startup."""

    _by_slug: dict[str, type[Skill]] = {}

    @classmethod
    def register(cls, skill_class: type[Skill]) -> type[Skill]:
        cls._by_slug[skill_class.slug] = skill_class
        return skill_class

    @classmethod
    def get(cls, slug: str) -> type[Skill]:
        if slug not in cls._by_slug:
            raise ValueError(f"unknown_skill: {slug}")
        return cls._by_slug[slug]

    @classmethod
    def list_for_aop(cls, allowed_slugs: list[str]) -> list[type[Skill]]:
        return [cls.get(s) for s in allowed_slugs]
```

### 5.3 Ejemplo concreto: `shopify.get_order_by_email`

```python
# apps/api/skills/shopify/get_order_by_email.py
from apps.api.skills.base import Skill, SkillInput, SkillOutput
from apps.api.skills.registry import SkillRegistry
from apps.api.integrations.shopify import ShopifyClient

class GetOrderByEmailInput(SkillInput):
    email: str

class OrderSummary(SkillOutput):
    order_number: str
    status: str
    total_price: float
    currency: str
    tracking_url: str | None

class GetOrderByEmailOutput(SkillOutput):
    orders: list[OrderSummary]

@SkillRegistry.register
class GetOrderByEmail(Skill):
    slug = "shopify.get_order_by_email"
    description = "Busca pedidos de Shopify por email del cliente. Devuelve hasta 10 más recientes."
    tier = "L1"
    input_schema = GetOrderByEmailInput
    output_schema = GetOrderByEmailOutput
    default_threshold = 0.70

    async def execute(self, ctx, inputs: GetOrderByEmailInput) -> GetOrderByEmailOutput:
        shopify = ShopifyClient(ctx.shopify_domain, ctx.shopify_token)
        raw_orders = await shopify.get_orders_by_email(inputs.email)
        return GetOrderByEmailOutput(
            orders=[OrderSummary(
                order_number=o["name"],
                status=o["financial_status"],
                total_price=float(o["total_price"]),
                currency=o["currency"],
                tracking_url=_first_tracking_url(o),
            ) for o in raw_orders]
        )
```

### 5.4 Tiers y comportamiento

| Tier | Naturaleza | Activación | Threshold default | Supervisor | Audit log |
|---|---|---|---|---|---|
| **L1** | Read-only | Día 1 con todo tenant | 0.70 | No | Trace en LangSmith; Langfuse queda como espejo secundario existente |
| **L2** | Write bajo riesgo | Día 1, opt-in en `tenant_tool_permissions` | 0.85 | Sonnet | Tabla dedicada |
| **L3** | Write alto riesgo (financiero, irreversible) | Tras 2-4 semanas, opt-in | 0.95 | Opus | Tabla dedicada + `human_approval_required` primer mes |

### 5.5 Skills planificadas para Shopify

| Slug | Tier | Sprint |
|---|---|---|
| `shopify.get_order_by_email` | L1 | 6 |
| `shopify.get_order_status` | L1 | 6 |
| `shopify.get_product_info` | L1 | 6 |
| `shopify.get_customer_history` | L1 | 6 |
| `shopify.get_shop_policies` | L1 | 6 |
| `shopify.add_order_note` | L2 | 9 |
| `shopify.create_draft_order` | L2 | 9 |
| `shopify.send_draft_invoice` | L2 | 9 |
| `shopify.update_shipping_address` | L3 | 10 |
| `shopify.cancel_order` | L3 | 10 |
| `shopify.refund_partial` | L3 | 10 |
| `shopify.start_return` | L3 | 10 |

---

## 6. Agent Operating Procedures (AOPs)

> Esta es la parte más densa del doc — el AOP es el corazón del comportamiento del agente.

### 6.1 Anatomía de un AOP

Cada AOP es un **documento estructurado con frontmatter YAML + cuerpo en markdown**. Inspirado en `SKILL.md` de Sierra pero adaptado al concepto de procedimiento (no de skill).

```yaml
---
slug: consulta_envio
name: "Consulta de estado de envío"
version: 3
workspace: production

# Cuándo se activa
triggers:
  description: >
    El cliente pregunta dónde está su pedido, cuándo llega, o pide tracking.
    Frases típicas: "dónde está mi pedido", "tracking de mi orden",
    "cuándo me llega", "no me ha llegado".
  keywords: ["tracking", "envío", "pedido", "orden", "llegada"]
  examples:
    - "Hola, hace una semana que ordené y no me ha llegado"
    - "Pueden darme el tracking de mi pedido #1234?"

# Qué puede hacer
allowed_skills:
  - shopify.get_order_by_email
  - shopify.get_order_status

# Datos que necesita para resolver
required_data:
  - customer_email   # debería venir de end_customer
  - order_number     # opcional, si el cliente lo da

# Reglas deterministas (el supervisor las verifica)
guardrails:
  - "NUNCA inventes un número de tracking. Si no hay tracking real, dilo."
  - "Si el cliente no provee email y no lo tenemos, pídelo antes de usar tools."

# Configuración runtime
max_tool_iterations: 3
confidence_threshold: 0.70
require_supervision: false   # L1 no requiere

# Cuándo escalar a humano
escalation_triggers:
  - "El pedido no aparece en Shopify"
  - "El cliente reclama por demora mayor a 7 días desde tracking"
  - "El cliente está enojado o usa lenguaje agresivo"
---

## Cómo te comportas

Cuando un cliente te pregunte por su pedido:

1. **Busca el pedido**. Usa `shopify.get_order_by_email` con el email del cliente.
   Si te dio el número de orden, úsalo con `shopify.get_order_status`.
2. Si encuentras **un solo pedido reciente**, asume que es ese.
3. Si encuentras **múltiples**, lista los últimos 3 con número y fecha,
   y pregúntale cuál.
4. Si encuentras tracking, comparte el link y di el courier.
5. Si **NO hay tracking aún**, di "se procesa típicamente en 24-48h hábiles".
6. Si el pedido tiene más de 7 días sin tracking, **escala**.

## Cierre

Termina ofreciendo ayuda adicional: "¿algo más en lo que te pueda ayudar?"
```

> **Tono NO va en el AOP.** El tono de voz pertenece al tenant — un AOP de cancelación o uno de envío para Lunaria deben sonar igual. El AOP solo describe **qué hacer**, no cómo suena. El tono se inyecta como Block A (identidad) desde `tenant_config.agent_voice` durante la compilación. Esto evita drift de voz entre AOPs y permite que cada cliente de Auyan tenga su propia personalidad sin tocar AOPs individuales.

### 6.2 Schema en base de datos

```sql
-- Tabla principal: metadata del AOP (cabecera)
CREATE TABLE aops (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL REFERENCES tenants(id),
    slug         TEXT NOT NULL,
    workspace    TEXT NOT NULL DEFAULT 'production',  -- 'production' | 'staging'
    current_version INT NOT NULL,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at   TIMESTAMPTZ,
    UNIQUE (tenant_id, slug, workspace)
);

-- Tabla de versiones (append-only, inmutable)
CREATE TABLE aop_versions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aop_id       UUID NOT NULL REFERENCES aops(id),
    version      INT NOT NULL,
    yaml_frontmatter JSONB NOT NULL,         -- parsed YAML
    body_markdown TEXT NOT NULL,             -- el "Cómo te comportas"
    raw_source   TEXT NOT NULL,              -- documento completo crudo (para diff)
    created_by   UUID REFERENCES users(id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (aop_id, version)
);

CREATE INDEX idx_aops_tenant_active ON aops(tenant_id, workspace)
    WHERE is_active = TRUE AND deleted_at IS NULL;
```

**Por qué append-only**: cada save crea una `aop_version` nueva. `aops.current_version` apunta a la activa. Nunca borramos versiones — desbloquea rollback instantáneo, A/B testing, audit forense.

### 6.3 Workspaces

- `production` — la que carga el grafo por default
- `staging` — para que el equipo de ops experimente sin tocar producción
- Cada (tenant, slug) puede tener su versión en cada workspace independientemente
- Promoción: `staging → production` es una operación explícita (botón en dashboard) que crea una nueva versión en production con el contenido de staging

### 6.4 Compilación en runtime — cómo se arma el system prompt

Este es el paso crítico: cómo el AOP se transforma en algo que Claude entiende.

```python
# apps/api/aops/compiler.py

async def compile_aop_to_runtime(
    aop: AOP,                                 # cargado de DB
    tenant_config: dict,
    retrieved_chunks: list[dict],
    skill_registry: SkillRegistry,
) -> CompiledAOP:
    """Compila un AOP a system prompt + tool definitions para Claude."""

    # 1. Resolver skills permitidas → Anthropic tool definitions
    skill_classes = skill_registry.list_for_aop(aop.frontmatter["allowed_skills"])
    tool_defs = [cls().to_anthropic_tool() for cls in skill_classes]

    # 2. Construir el system prompt en bloques
    blocks = [
        # Block A: identidad base del tenant
        _render_tenant_identity(tenant_config),

        # Block B: contexto del AOP (procedimiento + reglas)
        _render_aop_procedure(aop.body_markdown, aop.frontmatter),

        # Block C: guardrails determinísticos
        _render_guardrails(aop.frontmatter.get("guardrails", [])),

        # Block D: data points requeridos
        _render_required_data(aop.frontmatter.get("required_data", [])),

        # Block E: KB chunks (si hubo retrieval)
        _render_kb_chunks(retrieved_chunks) if retrieved_chunks else "",

        # Block F: reglas globales (escalation, tone fallback)
        _render_global_rules(),
    ]

    system_prompt = "\n\n---\n\n".join(b for b in blocks if b.strip())

    return CompiledAOP(
        system_prompt=system_prompt,
        tool_definitions=tool_defs,
        max_iterations=aop.frontmatter.get("max_tool_iterations", 5),
        confidence_threshold=aop.frontmatter["confidence_threshold"],
        require_supervision=aop.frontmatter.get("require_supervision", False),
        escalation_triggers=aop.frontmatter.get("escalation_triggers", []),
    )


def _render_aop_procedure(body: str, fm: dict) -> str:
    return (
        f"## Procedimiento: {fm['name']}\n\n"
        f"{body}"
    )


def _render_guardrails(guardrails: list[str]) -> str:
    if not guardrails:
        return ""
    lines = "\n".join(f"- {g}" for g in guardrails)
    return (
        "## Reglas NO negociables\n"
        "Estas reglas no las puedes romper bajo ninguna circunstancia:\n\n"
        f"{lines}"
    )
```

**System prompt final que ve Claude:**

```text
[BLOCK A — IDENTIDAD]
Eres el agente de soporte de Lunaria. Atiendes a clientes finales por email/web.
Hablas con tono cálido, tuteo caraqueño venezolano.

---

[BLOCK B — PROCEDIMIENTO]
## Procedimiento: Consulta de estado de envío
Cuando un cliente te pregunte por su pedido:
1. Busca el pedido. Usa shopify.get_order_by_email con el email del cliente...
[etc — el body markdown del AOP]

---

[BLOCK C — REGLAS NO NEGOCIABLES]
- NUNCA inventes un número de tracking...
- Si el cliente no provee email y no lo tenemos, pídelo antes de usar tools.

---

[BLOCK D — DATOS REQUERIDOS]
Necesitas estos datos para resolver:
- customer_email
- order_number (opcional)

---

[BLOCK E — KB] (si aplica)
Contexto adicional de la KB de Lunaria:
...

---

[BLOCK F — REGLAS GLOBALES]
Si en algún momento ves alguno de estos triggers, escala a humano:
- El pedido no aparece en Shopify
- El cliente está enojado o usa lenguaje agresivo
- ...
```

Y las **tools** llegan al API call como el array `tools=[...]` con SOLO `get_order_by_email` y `get_order_status` (no todas las skills del tenant — esto es lo que reduce alucinaciones).

### 6.5 Caching

Cargar y compilar el AOP en cada request sería desperdicio. Plan:

```python
# TTL cache de 60 segundos para AOPs por (tenant_id, slug, workspace)
_AOP_CACHE: TTLCache = TTLCache(maxsize=1000, ttl=60)
```

60s permite hot-reload casi instantáneo desde el dashboard (peor caso 1 min de delay), pero evita hammers a DB.

**Problema multi-worker:** cada worker de Railway tiene su propia cache en memoria. Un usuario edita en el dashboard → save → prueba inmediatamente y cae en otro worker que aún sirve la versión vieja → cree que su edit falló y lo guarda de nuevo. Mitigaciones (en orden de complejidad):

1. **Sprint 7 (MVP):** UI del editor muestra explícitamente "los cambios pueden tardar hasta 60s en propagar a todos los workers" + botón "test inmediato" que carga la versión cruda de DB sin cache (bypass).
2. **Sprint 9+:** invalidación explícita por Redis pub/sub: al guardar una nueva versión, publish a `aop:invalidate:{tenant_id}:{slug}` y cada worker drop la key.
3. **Alternativa si no queremos Redis:** notificación por canal de Postgres (`LISTEN/NOTIFY`) en una conexión persistente por worker.

Decisión por ahora: empezar con (1) para Sprint 7, escalar a (2) cuando lleguemos a >3 workers o cuando alguien se queje.

### 6.6 Ejemplo de segundo AOP: cancelación

```yaml
---
slug: cancelacion
name: "Cancelación de pedido"
version: 1
workspace: production

triggers:
  description: "El cliente quiere cancelar un pedido que aún no fue enviado."
  keywords: ["cancelar", "anular", "no quiero", "devuelvan mi dinero"]

allowed_skills:
  - shopify.get_order_by_email
  - shopify.get_order_status
  - shopify.cancel_order        # ← L3, requiere supervisor

required_data:
  - customer_email
  - order_number

guardrails:
  - "NUNCA canceles sin verificar primero que el pedido NO esté en estado 'fulfilled'."
  - "SIEMPRE pide confirmación explícita al cliente antes de ejecutar cancel_order."
  - "Si el pedido fue parcialmente enviado, NO uses cancel_order. Escala."

max_tool_iterations: 5
confidence_threshold: 0.95     # ← L3 threshold
require_supervision: true      # ← obliga al supervisor Opus

escalation_triggers:
  - "Pedido fulfilled o parcialmente enviado"
  - "Pedido con multiple line items con states mixtos"
  - "Cliente reclama daños o defectos"
---

## Cómo te comportas

1. Busca el pedido con `shopify.get_order_by_email`.
2. Verifica estado con `shopify.get_order_status`.
3. Si el estado es `fulfilled` o `partially_fulfilled` → **ESCALA**, no canceles.
4. Si está `paid` y no fulfilled, **confirma con el cliente**:
   "Voy a cancelar tu pedido #X por $Y. Esto disparará un reembolso
   en 5-7 días hábiles al método de pago original. ¿Confirmas?"
5. Solo después de confirmación explícita, usa `shopify.cancel_order`.
6. Después de cancelar, explícale el reembolso.

## Sobre el tono de este AOP

La cancelación es una decisión importante para el cliente — no la trates frívolamente.
Tono base sigue siendo el del tenant (ver `tenant_config.agent_voice`),
pero baja la intensidad y prioriza claridad sobre calidez.
```

Nota cómo este AOP:
- Tiene `require_supervision: true` → fuerza el nodo `supervise` con Opus
- Tiene `threshold: 0.95` → si confidence < 95%, escala
- Tiene guardrails que el supervisor verifica explícitamente

---

## 7. Selector de intent — nodo `select_aop`

Hoy no tenemos clasificador de intent. La v2 lo introduce.

### 7.1 Diseño

```python
# apps/api/agents/nodes/select_aop.py

async def select_aop(state: AgentState, deps: AgentDependencies) -> dict:
    # 1. Cargar catálogo de AOPs activos del tenant (cached)
    aops = await load_active_aops(
        tenant_id=state["tenant_id"],
        workspace="production",
    )

    # 2. Construir prompt de clasificación
    catalog = [
        {"slug": a.slug, "name": a.name, "description": a.frontmatter["triggers"]["description"]}
        for a in aops
    ]

    # 3. Llamar a Haiku con tool forzado
    response = await deps.anthropic.call_with_tool(
        model="claude-haiku-4-5",
        system=INTENT_CLASSIFIER_PROMPT,  # prompt fijo, no del tenant
        messages=[{
            "role": "user",
            "content": (
                f"Catálogo de procedimientos disponibles:\n{json.dumps(catalog, indent=2)}\n\n"
                f"Mensaje del cliente:\n{state['inbound_message_content']}\n\n"
                f"Historial reciente:\n{format_history(state['conversation_history'][-3:])}"
            ),
        }],
        tool=SELECT_AOP_TOOL,
    )

    parsed = ClassifierOutput.model_validate(response.tool_input)

    # 4. Fallback a default si confidence baja
    if parsed.confidence < deps.settings.intent_min_confidence:
        return {
            "aop_slug": "default",
            "aop_version": (await load_aop("default")).version,
            "intent_confidence": parsed.confidence,
        }

    return {
        "aop_slug": parsed.slug,
        "aop_version": next(a.version for a in aops if a.slug == parsed.slug),
        "intent_confidence": parsed.confidence,
    }
```

### 7.2 Tool definition para el clasificador

El clasificador devuelve **top-2 candidatos con confidence**, no solo el primero. Esto desbloquea auditoría posterior y detección de ambigüedad. La elección runtime usa el top-1; el top-2 se persiste en `intent_alternatives` para que el slow agent pueda analizar misclassifications.

```python
SELECT_AOP_TOOL = {
    "name": "select_aop",
    "description": "Selecciona el procedimiento más apropiado para el mensaje del cliente.",
    "input_schema": {
        "type": "object",
        "properties": {
            "primary": {
                "type": "object",
                "properties": {
                    "slug": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["slug", "confidence"],
            },
            "alternative": {
                "type": "object",
                "description": "Segundo candidato más probable, null si no hay duda razonable.",
                "properties": {
                    "slug": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["slug", "confidence"],
            },
            "reasoning": {"type": "string", "description": "Por qué elegiste el primary en 1-2 frases"},
            "ambiguity_detected": {
                "type": "boolean",
                "description": "True si el mensaje contiene múltiples intents claramente distintos.",
            },
        },
        "required": ["primary", "reasoning", "ambiguity_detected"],
    },
}
```

### 7.3 Persistencia del AOP entre turnos

**Por defecto, NO reclasificar en cada turno** — esto destruye contexto. Reglas:

```python
def should_reclassify(state: AgentState) -> bool:
    # Primer turno de la conversación → clasificar
    if state.get("aop_slug") is None:
        return True
    # AOP locked por turnos (ej: en medio de cancelación con confirmación pendiente)
    if state.get("aop_locked_until_turn"):
        current_turn = len([m for m in state["conversation_history"] if m["role"] == "customer"])
        if current_turn < state["aop_locked_until_turn"]:
            return False
    # Si el AOP en curso terminó su flujo (cliente dijo "gracias, listo") → reclasificar
    if state.get("aop_completed_signal"):
        return True
    # Heurística: si el último mensaje del cliente no matchea triggers del AOP actual → reclasificar
    return _message_drifted_from_current_aop(state)
```

El AOP puede declarar en su frontmatter `lock_for_turns: 3` para forzar persistencia (ej: AOP `cancelacion` lockea hasta que se confirma/rechaza). Si después del lock el cliente cambió de tema, se reclasifica.

### 7.4 Multi-intent en un solo mensaje

Si `ambiguity_detected: true` y ambos `confidence > 0.6`, el agente NO debe asumir uno. Comportamiento:
1. Responder primero al primary intent (el más urgente o el primero mencionado).
2. **Reconocer explícitamente el segundo**: "También vi que mencionaste X — atendemos eso después de resolver esto, ¿te parece?"
3. Persistir `pending_intent: <slug del alternative>` en la conversación para el siguiente turno.

Esto evita el caso clásico que mencionaste ("hola, dónde está mi pedido y también quiero cancelar el otro").

### 7.5 Métricas obligatorias del clasificador

Trackear desde el día 1 en LangSmith + tabla `intent_classifier_runs`:

| Métrica | Cómo se mide | Acción si se desvía |
|---|---|---|
| `intent_confidence_distribution` | histograma de `primary.confidence` por AOP | Si un AOP tiene mediana <0.7, sus triggers están mal escritos |
| `intent_misclassification_rate` | % de turnos donde un humano corrigió el AOP (vía dashboard) o el slow agent lo flaggeó | >5% → revisar triggers urgente |
| `intent_ambiguity_rate` | % con `ambiguity_detected=true` | Si >15%, considerar dividir AOPs muy similares |
| `intent_fallback_rate` | % que cayeron al AOP `default` por baja confidence | Si >10% → faltan AOPs |
| `intent_reclassification_rate` | % de turnos no-primero donde se reclasificó | Si es alto, el `should_reclassify` está flapeando |

```sql
CREATE TABLE intent_classifier_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    conversation_id UUID NOT NULL,
    turn_number     INT NOT NULL,
    primary_slug    TEXT NOT NULL,
    primary_confidence NUMERIC(3,2) NOT NULL,
    alternative_slug TEXT,
    alternative_confidence NUMERIC(3,2),
    ambiguity_detected BOOLEAN NOT NULL,
    was_reclassification BOOLEAN NOT NULL,
    human_correction TEXT,                         -- si un humano cambió el AOP, qué eligió
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 7.6 AOP `default` (obligatorio por tenant)

Siempre debe existir un AOP `slug=default` con:
- `allowed_skills: []` (sin acciones, solo respuesta basada en KB)
- `confidence_threshold: 0.85`
- Comportamiento: responder con info de la KB, escalar si no hay info suficiente

Es el fallback cuando ningún AOP específico aplica.

### 7.7 Por qué LLM y no embeddings

Consideramos embedding router (más rápido, más barato). Decisión: LLM por ahora.

- **Pro embeddings**: 10x más barato, sub-100ms latencia
- **Contra**: clasificación de intent en CX no es solo similitud semántica — depende de contexto conversacional ("ya me dijiste el tracking, ahora pregunto por devolución"). Un LLM lo entiende, embeddings no.
- **Plan futuro**: añadir embedding router como pre-filtro (Sprint 13+). Si embedding tiene confidence >0.9, saltarse Haiku.

---

## 8. Supervisor pattern

### 8.1 Cuándo se activa

```python
def needs_supervision(state: AgentState) -> bool:
    aop = state.get("compiled_aop")
    # 1. AOP marca require_supervision explícitamente
    if aop.require_supervision:
        return True
    # 2. La decisión propuesta involucra una tool L2+
    if state.get("pending_tool_call"):
        skill = SkillRegistry.get(state["pending_tool_call"]["name"])
        if skill.tier in ("L2", "L3"):
            return True
    return False
```

### 8.2 Selección de modelo

| Contexto | Modelo supervisor |
|---|---|
| AOP requiere supervisión sin tools | `claude-sonnet-4-6` |
| Tool L1 | (no se llama supervisor) |
| Tool L2 | `claude-sonnet-4-6` |
| Tool L3 | `claude-opus-4-7` |

### 8.3 Qué evalúa exactamente

El supervisor recibe (vía API call):

```text
ROL: Eres el supervisor del agente conversacional. Tu trabajo es evaluar
si la decisión propuesta por el agente principal es correcta antes de ejecutarse.

CONTEXTO DEL AOP:
[el AOP completo que está usando el agente]

GUARDRAILS DEL AOP:
[lista de guardrails — chequearlos UNO POR UNO]

HISTORIAL DE LA CONVERSACIÓN:
[mensajes anteriores]

REASONING DEL AGENTE PRINCIPAL:
[lo que Claude propuso hacer + por qué]

TOOLS QUE QUIERE EJECUTAR:
[lista de tool calls pendientes con sus inputs]

RESPUESTA PROPUESTA AL CLIENTE:
[el draft de respuesta, si hay]

PREGUNTAS QUE DEBES RESPONDER:
1. ¿La decisión respeta TODOS los guardrails del AOP?
2. ¿Los tool inputs son correctos y derivan del contexto (no inventados)?
3. ¿La respuesta al cliente está respaldada por evidencia real?
4. ¿Hay algún edge case en escalation_triggers que el agente ignoró?

DECISIÓN: usar tool `supervisor_verdict`
```

### 8.4 Schema del verdict — tactical vs structural

El supervisor distingue **por qué** rechaza. Esto define si vale la pena reintentar o si hay que escalar directo.

```python
SUPERVISOR_VERDICT_TOOL = {
    "name": "supervisor_verdict",
    "description": "Aprobar o rechazar la decisión del agente principal.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["approve", "reject"]},
            "reject_kind": {
                "type": "string",
                "enum": ["tactical", "structural", "n/a"],
                "description": (
                    "tactical = el agente puede arreglar reintentando "
                    "(ej: 'olvidó verificar fulfillment'). "
                    "structural = el AOP no aplica o falta capability; "
                    "reintentar no ayuda (ej: 'este caso requiere humano')."
                ),
            },
            "reason": {
                "type": "string",
                "description": "Explicación de 1-2 frases. Si reject, qué arreglar.",
            },
            "guardrails_violated": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Lista de guardrails específicos que se violaron.",
            },
        },
        "required": ["verdict", "reject_kind", "reason"],
    },
}
```

**Reglas de routing** (también en sección 3.4):
- `approve` → continúa al destino (respond/escalate/execute_skill)
- `reject + structural` → escala directo al humano, **sin reintento** (ahorra tokens y latencia)
- `reject + tactical` (primer rechazo) → vuelve a `reason` con `supervisor_reason` inyectado al contexto
- `reject + tactical` (segundo rechazo) → escala al humano

### 8.5 Métricas a trackear

- `supervisor_override_rate` (% de rejects sobre total) — si >20%, el AOP necesita mejora
- `supervisor_override_rate_by_kind` — desglose tactical vs structural; mucho structural = problemas de routing del intent classifier, mucho tactical = AOPs ambiguos
- `supervisor_latency_p50/p95` — Opus puede ser lento
- `supervisor_cost_per_conversation` — Opus es caro
- `write_error_rate_with_supervisor` vs `write_error_rate_without_supervisor` — la métrica honesta que reemplaza la fake "99%". A medir mediante shadow runs en Sprint 8+.

Si override_rate baja a <2% durante un mes, podemos considerar bajar supervisor a Sonnet para ese AOP.

---

## 9. Eval harness — obligatorio desde Sprint 7

Sin evals automatizados, todo lo demás del doc es teoría peligrosa: el slow agent propondrá cambios que no se pueden validar, el A/B testing usará clientes reales como conejillos de indias, y cualquier cambio al supervisor prompt es un salto al vacío. Esta sección es **obligatoria, no opcional**.

### 9.1 Estructura

```
apps/api/evals/
├── harness.py                  # runner que ejecuta el grafo contra mocks
├── mocks/
│   ├── shopify_mock.py         # responses canónicos por escenario
│   └── kb_mock.py              # KB con docs deterministas
├── fixtures/
│   ├── consulta_envio/         # carpeta por AOP
│   │   ├── 001_happy_path.yaml
│   │   ├── 002_multiple_orders.yaml
│   │   ├── 003_no_tracking_yet.yaml
│   │   ├── 004_order_not_found.yaml
│   │   └── ...
│   ├── cancelacion/
│   └── default/
└── assertions.py               # helpers: assert_tool_called, assert_escalated, etc.
```

### 9.2 Schema de un fixture

```yaml
# evals/fixtures/cancelacion/007_already_fulfilled.yaml
name: "Cancelación rechazada porque pedido ya fue enviado"
aop_expected: cancelacion
tenant_id: lunaria-test

# Setup del estado del mundo
mocks:
  shopify:
    get_order_by_email:
      input: {email: "ana@example.com"}
      response:
        orders:
          - order_number: "#1234"
            financial_status: paid
            fulfillment_status: fulfilled  # ← clave del test

# Input del cliente
inbound:
  customer_email: ana@example.com
  message: "Hola, quiero cancelar mi pedido #1234"

# Outcome esperado
expectations:
  decision: escalate                       # debe escalar, NO usar cancel_order
  escalation_reason_contains: ["fulfilled", "enviado"]
  tools_must_be_called: [shopify.get_order_status]
  tools_must_NOT_be_called: [shopify.cancel_order]
  response_must_NOT_contain: ["cancelado", "reembolso procesado"]
  supervisor_should_intervene: false       # nunca llega al supervisor — escala antes
```

### 9.3 Cuándo corren

| Trigger | Qué corre | Política de gate |
|---|---|---|
| Pre-commit (local) | Solo fixtures del AOP modificado | Warning si fallan, no bloquea commit |
| PR a `develop` (CI) | Suite completa | **Bloqueante**: si falla, no se mergea |
| Antes de promover AOP `staging → production` | Suite completa del AOP + smoke regression | **Bloqueante**: botón de promote queda deshabilitado |
| Antes de aplicar propuesta del slow agent | Suite completa | **Bloqueante**: la propuesta queda en `requires_eval_pass` |
| Nightly | Suite completa + métricas históricas | No bloquea, alerta si trend baja |

### 9.4 Inventario mínimo por AOP

Cada AOP nuevo debe tener al menos:
- 5 happy paths (variaciones del flujo esperado)
- 3 edge cases (datos faltantes, multiple matches, formato inesperado)
- 3 escalation triggers (casos donde DEBE escalar)
- 2 adversarial (intentos de manipulación, prompts injection, datos PII expuestos)

Mínimo total por AOP: **13 fixtures**. Si un AOP no llega a esto, no puede pasar a `production` workspace.

### 9.5 LLM-as-judge para fixtures cualitativos

Algunos asserts son booleanos simples (`tools_must_be_called`). Otros son cualitativos ("la respuesta es empática"). Para esos:

```yaml
expectations:
  response_judge:
    criteria:
      - "Reconoce explícitamente la frustración del cliente"
      - "Ofrece una acción concreta, no solo disculpas"
      - "No promete plazos imposibles (24h, mismo día)"
    judge_model: claude-sonnet-4-6   # judge, no Opus por costo
    pass_threshold: 2_of_3           # debe cumplir al menos 2 de 3
```

El judge se reusa luego en el slow agent (sección 14).

### 9.6 Sprint plan

- **Sprint 7 (obligatorio):** harness funcional + mocks Shopify + 13 fixtures para `consulta_envio` y `default`. Sin esto, AOPs no pueden promoverse.
- **Sprint 9:** 13 fixtures por cada skill L2 nueva.
- **Sprint 10:** 13 fixtures por cada skill L3 nueva, con énfasis en adversarial.

---

## 10. Tool permissions y feature flags

### 10.1 Tabla de permisos por tenant

```sql
CREATE TABLE tenant_tool_permissions (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenants(id),
    skill_slug    TEXT NOT NULL,
    is_enabled    BOOLEAN NOT NULL DEFAULT FALSE,
    threshold_override NUMERIC(3,2),         -- override del default del skill
    human_approval_required BOOLEAN NOT NULL DEFAULT FALSE,
    enabled_at    TIMESTAMPTZ,
    enabled_by    UUID REFERENCES users(id),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, skill_slug)
);

-- Default rows seedeadas al crear un tenant:
--   L1: is_enabled=TRUE
--   L2: is_enabled=FALSE
--   L3: is_enabled=FALSE, human_approval_required=TRUE
```

### 10.2 Verificación en runtime

```python
async def filter_allowed_skills(
    tenant_id: UUID,
    aop_allowed: list[str],
) -> list[str]:
    """Filtra skills del AOP según permisos del tenant."""
    perms = await get_tool_permissions(tenant_id, aop_allowed)
    return [
        slug for slug in aop_allowed
        if perms.get(slug, False)  # default False si no hay row
    ]
```

Si un AOP declara `allowed_skills: [shopify.cancel_order]` pero el tenant tiene `cancel_order.is_enabled=False`, esa skill simplemente no se le presenta al LLM. Si el AOP queda sin skills útiles, el agente actuará en modo conversacional o escalará.

---

## 11. Audit log de skills

### 11.1 Schema

```sql
CREATE TABLE skill_audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id),
    conversation_id UUID NOT NULL REFERENCES conversations(id),
    aop_slug        TEXT NOT NULL,
    aop_version     INT NOT NULL,
    skill_slug      TEXT NOT NULL,
    skill_tier      TEXT NOT NULL,                  -- L1 | L2 | L3
    idempotency_key UUID,                           -- NULL para L1
    inputs_redacted JSONB NOT NULL,                 -- ver 11.3 política PII
    outputs_redacted JSONB,                         -- NULL si falló, ver 11.3
    inputs_hash     TEXT NOT NULL,                  -- sha256 del original para forense
    confidence      NUMERIC(3,2),                   -- del LLM
    supervisor_verdict TEXT,                        -- approve | reject | null
    status          TEXT NOT NULL,                  -- success | failed | rejected_by_supervisor | rejected_by_permissions
    error_message   TEXT,
    latency_ms      INT,
    langfuse_trace_id TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_tenant_time ON skill_audit_log(tenant_id, created_at DESC);
CREATE INDEX idx_audit_idempotency ON skill_audit_log(tenant_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
```

L1 también escribe acá (sin idempotency_key) para tener vista unificada en el dashboard.

### 11.2 Vista en dashboard

Lista filtrable por tenant + AOP + skill + status + rango de fechas. Útil para:
- Debug post-hoc cuando un cliente reclama
- Detectar AOPs que generan muchos failures
- Verificar que skills nuevas funcionan en producción

### 11.3 Política de PII (obligatoria, NO TBD)

Estamos basados en España → GDPR aplica. Toda skill que reciba PII (email, teléfono, dirección, nombre, IDs externos del cliente) debe declarar sus campos PII en el schema de input.

```python
class GetOrderByEmailInput(SkillInput):
    email: str = Field(..., pii=True, pii_kind="email")  # marcador en el schema
```

**Reglas de persistencia**:

| Campo | En audit log (`inputs_redacted`) | En `inputs_hash` | En trazas LangSmith/Langfuse |
|---|---|---|---|
| Email | pseudonimizado: `sha256(email + tenant_salt)[:16]` | hash original (para detección de duplicados) | mismo pseudónimo que audit log |
| Teléfono | últimos 4 dígitos `***-1234` | hash | últimos 4 dígitos |
| Nombre | iniciales `J. P.` | hash | iniciales |
| Order number, IDs no-PII | tal cual (no son PII) | hash | tal cual |
| Free text del cliente | tal cual hasta 200 chars + `[truncated]` | hash | tal cual |

**Salt por tenant**: cada tenant tiene un `tenant_pii_salt` random de 32 bytes en una tabla `tenant_secrets` (no en `tenants` que es más pública). Esto permite "olvido" GDPR: rotar el salt invalida todos los pseudónimos históricos del tenant.

**Acceso al audit log**: 
- `super_admin` Auyan → ve datos pseudonimizados por default; puede pedir "desanonimizar conversación X" (acción registrada en otra tabla `pii_access_log`)
- `tenant_admin` → ve solo audit log de su tenant, ya pseudonimizado
- Engineers de Auyan → mismo nivel que super_admin

**Retención**: audit log retiene 90 días en hot (Postgres), exporta a S3/cold después. Hash original se purga a los 180 días salvo orden legal.

Decidir antes de Sprint 9: ¿usamos `pgcrypto` para hashing in-DB o lo hacemos en app? Voto: en app, así el salt nunca toca Postgres logs.

---

## 12. Idempotency

### 12.1 Estrategia

Toda skill L2/L3 declara `requires_idempotency=True`. El nodo `execute_skill`:

1. **Genera el idempotency_key ANTES de llamar a la skill** (UUIDv7, generado por nosotros, NUNCA por el LLM).
2. **Insert en `skill_idempotency`** con `(tenant_id, skill_slug, idempotency_key, inputs_hash)`.
3. Si ya existe una row con el mismo `idempotency_key`, devuelve el `output_cache` guardado (no re-ejecuta).
4. Si no existe, ejecuta, persiste output en la misma row.

```sql
CREATE TABLE skill_idempotency (
    tenant_id        UUID NOT NULL,
    skill_slug       TEXT NOT NULL,
    idempotency_key  UUID NOT NULL,
    inputs_hash      TEXT NOT NULL,         -- sha256(canonical_json(inputs))
    output_cache     JSONB,
    status           TEXT NOT NULL,         -- pending | success | failed
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at     TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, skill_slug, idempotency_key)
);
```

### 12.2 Cuándo se genera el key

- En `execute_skill`, justo antes de llamar a `skill.execute()`.
- El key se persiste en `tool_results` del state para que aparezca en el audit log.

### 12.3 Inputs hash

Es defensa: si en un retry el LLM cambia inputs (por bug nuestro o por reasoning distinto), detectamos mismatch. Si `inputs_hash` no coincide con el guardado, **falla con error explícito** — no ejecutamos algo distinto a lo que prometimos.

---

## 13. Lifecycle de la conversación — cuándo cerrar por abandono

Hoy una conversación que el cliente abandona queda en `open` para siempre. Esto rompe métricas (resolution_rate inflado), llena el inbox con ruido, y bloquea capacity de los agentes humanos que ven "tickets pendientes" que en realidad nadie está esperando.

### 13.1 Estados de cierre

Extender el enum de `conversations.status` con un cierre explícito por timeout:

```
open                              → activa
pending_customer_response         → el agente preguntó, esperando al cliente
resolved                          → cliente confirmó o flujo completó OK
escalated                         → handoff a humano (estado existente)
closed_by_customer                → el cliente dijo "gracias, listo" o equivalente
closed_abandoned                  → NUEVO: cerrada por timeout sin respuesta
```

`closed_abandoned` es distinto de `resolved` deliberadamente — para métricas separadas (abandonment_rate vs resolution_rate).

### 13.2 Timeouts por canal — viven en `tenant_config`

Cada canal tiene su ritmo natural. Defaults razonables que el tenant puede override:

```yaml
# tenant_config.conversation_lifecycle
abandonment_timeouts:
  email:                7d         # email es asíncrono por naturaleza
  zendesk:              7d         # mismo
  chat_widget:          30m        # chat es sincrónico
  whatsapp:             24h        # intermedio
  instagram_dm:         48h        # intermedio
  sms:                  4h         # rápido pero no instantáneo

# Después de cuántas horas en pending_customer_response el agente envía un nudge
nudge_after:
  email:                72h        # "¿sigues necesitando ayuda con esto?"
  zendesk:              72h
  chat_widget:          null       # nunca nudgeamos chat
  whatsapp:             12h
  instagram_dm:         24h
  sms:                  2h
```

### 13.3 Job de cierre

Cron cada 15 minutos:

```python
# apps/api/jobs/conversation_lifecycle.py
async def close_abandoned_conversations():
    for tenant in await list_active_tenants():
        timeouts = tenant.config["conversation_lifecycle"]["abandonment_timeouts"]
        for channel, timeout in timeouts.items():
            cutoff = now() - parse_duration(timeout)
            convs = await fetch_conversations_to_close(
                tenant_id=tenant.id,
                channel=channel,
                status_in=("open", "pending_customer_response"),
                last_message_at_lt=cutoff,
            )
            for c in convs:
                await close_conversation_as_abandoned(
                    conn,
                    conversation_id=c.id,
                    reason=f"abandoned_after_{timeout}_no_customer_response",
                )
                # Mensaje silencioso al sistema (no se envía al cliente):
                await insert_message(
                    conn,
                    conversation_id=c.id,
                    role="system",
                    direction="internal",
                    content=f"Conversación cerrada automáticamente por inactividad ({timeout}).",
                )
```

### 13.4 Nudge antes de cerrar (opcional, opt-in por canal)

Si el cliente no respondió pero estamos a mitad del timeout, mandar 1 nudge:

```
"Hola, sigues necesitando ayuda con lo del pedido #1234?
Si no me dices nada en las próximas 24h cerramos esto, pero
puedes responder en cualquier momento y lo retomamos."
```

El nudge es **una sola vez**. Si vuelve a haber timeout sin respuesta → close. Tracking: tabla `conversation_nudges` para no duplicar.

### 13.5 Reapertura

Si después de `closed_abandoned` el cliente vuelve a escribir (mismo email/external_id) → la lógica `find_conversation_by_external` en webhooks.py debe excluir conversaciones cerradas, **creando una nueva conversación** vinculada (campo `previous_conversation_id`) — esto da contexto al agente sin reusar el thread cerrado.

### 13.6 Métricas

- `abandonment_rate` por tenant y por canal — si es alto, los AOPs piden demasiada info o los tiempos de respuesta del agente son largos.
- `nudge_recovery_rate` — % de nudges que generan respuesta del cliente. Si <5%, el nudge es ruido y conviene desactivarlo.
- `reopen_rate` — % de clientes que vuelven después de un abandon. Alto = el agente cerró conversaciones que el cliente sí seguía necesitando.

### 13.7 Sprint plan

- **Sprint 6 o 8 (rápido, idealmente 6):** estado `closed_abandoned` + job de cierre simple con defaults globales (sin per-tenant config aún) + métrica básica. Sin nudges.
- **Sprint 9:** `tenant_config.conversation_lifecycle` editable + nudges opt-in.
- **Sprint 12:** integrar a la lógica de reapertura con `previous_conversation_id`.

---

## 14. Slow agent (Sprint 11)

### 14.1 Cambio de plan vs propuesta original

La propuesta inicial de correr Opus sobre TODAS las conversaciones cada noche es financieramente irresponsable a escala. Math rápida que justifica el cambio:

```
10 tenants × 200 conv/día × ~5k tokens input Opus
= 10M tokens/día solo input
≈ $150-200/día (precios 2026)
≈ $4.5k-6k/mes antes de tener ARR que lo respalde
```

Plan revisado para Sprint 11: **arrancar pequeño, validar ROI antes de escalar**.

### 14.2 Plan revisado por fase

| Fase | Cuándo | Cobertura | Modelo judge | Cadencia |
|---|---|---|---|---|
| **Skeleton (Sprint 11)** | Mes 1 | Solo escaladas + sample 10% resueltas con tools L2/L3 | Sonnet | Semanal manual primero, luego nightly |
| **Validación (Sprint 12-13)** | Mes 2-3 | Todas las escaladas + 100% L2/L3 + 5% sample resueltas | Sonnet con escalación a Opus en casos marcados `uncertain` | Nightly |
| **Producción (Sprint 14+)** | Cuando proposal acceptance_rate >40% sostenido | Todas las conversaciones | Sonnet default, Opus solo en `uncertain` (~5-10%) | Nightly |

### 14.3 Sampling strategy

```python
def should_judge(conv: Conversation) -> bool:
    # Siempre juzgar:
    if conv.status == "escalated":
        return True
    if conv.tools_used_l2_l3:
        return True
    # Sample random del resto
    return hashlib.sha256(f"{conv.id}:{date.today()}".encode()).digest()[0] < 25  # ~10%
```

### 14.4 Two-step judging (Sonnet → Opus solo si necesario)

```python
sonnet_verdict = await judge_with_sonnet(conv)
if sonnet_verdict.confidence < 0.7 or sonnet_verdict.flag_for_opus:
    final_verdict = await judge_with_opus(conv)
else:
    final_verdict = sonnet_verdict
```

Esto baja el costo Opus al ~5-10% de los casos.

### 14.5 Tabla de propuestas

```sql
CREATE TABLE improvement_proposals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id),
    proposal_type   TEXT NOT NULL,                  -- aop_edit | new_aop | skill_request | guardrail_addition
    aop_slug        TEXT,                           -- NULL si new_aop o skill_request
    diff_markdown   TEXT NOT NULL,                  -- diff propuesto o documento completo
    rationale       TEXT NOT NULL,
    evidence_conversations UUID[] NOT NULL,
    judge_model_used TEXT NOT NULL,                 -- sonnet | opus
    judge_confidence NUMERIC(3,2) NOT NULL,
    requires_eval_pass BOOLEAN NOT NULL DEFAULT TRUE, -- gate con harness sección 9
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected | applied
    reviewed_by     UUID REFERENCES users(id),
    reviewed_at     TIMESTAMPTZ,
    applied_version INT,                            -- versión del AOP creada al aprobar
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

`requires_eval_pass` enlaza con el harness de sección 9: ninguna propuesta se aplica sin pasar evals.

### 14.6 UI

En dashboard interno: cola de propuestas pendientes con preview del diff. Aprobar = crea una nueva versión del AOP. Rechazar = guarda razón.

### 14.7 Métricas de salud del slow agent

- `proposal_acceptance_rate` — % de propuestas aprobadas por humanos. <20% = el judge propone basura, ajustar prompt. >60% sostenido = el judge encontró su voz.
- `cost_per_useful_proposal` = costo Opus mensual / propuestas aprobadas. Si supera $50, repensar.
- `time_to_first_proposal_per_tenant` — cuántos días desde onboarding hasta primera propuesta accionable.

---

## 15. Versionado y A/B testing (Sprint 13)

Cada `aop_versions` row es inmutable. Para A/B:

```sql
CREATE TABLE aop_traffic_split (
    id                UUID PRIMARY KEY,
    tenant_id         UUID NOT NULL,
    aop_slug          TEXT NOT NULL,
    workspace         TEXT NOT NULL DEFAULT 'production',
    version_a         INT NOT NULL,
    version_b         INT NOT NULL,
    pct_to_b          INT NOT NULL CHECK (pct_to_b BETWEEN 0 AND 100),
    started_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at          TIMESTAMPTZ
);
```

El loader del AOP hashe `conversation_id` y rutea según split. Esto permite test estable (mismo cliente siempre ve la misma versión).

Métricas comparativas: CSAT, resolution_rate, escalation_rate, cost_per_conversation, supervisor_override_rate.

---

## 16. Plan por sprints (actualizado post pivot 2026-05-22)

### Sprints completados ✅

| Sprint | Foco | Entrega |
|---|---|---|
| **6** ✅ | Skills framework + Shopify read tools + ReAct loop **+ lifecycle básico** | 5 skills L1, grafo refactorizado, credenciales Shopify por tenant, estado `closed_abandoned` |
| **7** ✅ | AOPs en DB + selector de intent + workspaces + UI básica **+ eval harness obligatorio** | Tablas, compiler, `select_aop` node, editor dashboard, harness con 13 fixtures |
| **8** ✅ | Supervisor pattern + Agent Reasoning UI | Nodo `supervise`, schema tactical/structural, métricas de observabilidad, UI reasoning panel |
| **9** ✅ | Skills L2 + permissions + audit log PII + idempotency + nudges + cache invalidation | 2 skills L2, audit log pseudonimizado, AOP cache invalidation NOTIFY |
| **10** ✅ | Skills L3 + human approval mode + UI de aprobación | 4 skills L3, flujo aprobación, idempotency, 52 fixtures adversarial |
| **11** ✅ | Slow agent skeleton (sampling + Sonnet judge) | Job semanal manual, sampling, tabla proposals, UI cola, two-step judge |
| **A.1-A.4** ✅ | Rate limiting + budget gate + message limit + usage UI | Bloqueadores de producción resueltos |

### PIVOT 2026-05-22 — del modelo BPO al Managed AI Service

El "Sprint 12 — Unified KB + Zendesk bidireccional + reapertura" fue **descartado/reformulado** en el grill-me del 2026-05-22. Razón:

- **Zendesk bidireccional** sigue siendo necesario PERO ahora como parte de **patrón Adapter por tenant** (no integración hardcoded). Va en Bloque 0.
- **Unified KB** (pipeline humano→KB) se reformula como **drop-zone del cliente con curación Auyan** + tabla `tenant_playbook` (NO Notion). Va en Bloque 1.
- **Reapertura de conversaciones** (`previous_conversation_id`) se mantiene como deuda técnica pequeña, queda en Bloque 4 backlog.

El plan post-pivot se organiza en **Bloques 0-3** que reflejan el nuevo modelo Managed AI Service. Pendientes y backlog en `docs/architecture-overview.md` §5.

### Bloques post-pivot

| Bloque | Foco | Entrega clave |
|---|---|---|
| **0** | Sanity check + fundación arquitectónica (3-4 sem) | Hard removal `tenant_agent`, framework adapters (`MessageProvider` + `HelpdeskProvider`), 4 adapters (Shopify + Chatwoot + Zendesk + Gorgias + Postmark outbound), roles internos estructura DB, AOPs `steps[]` opcional, **Simulator MVP con judge 4-dim**, validación E2E |
| **1** | Sprint A — habilita vender (5-7 sem) | **Design Sprint** (DESIGN.md), onboarding guiado por invitación (9 pasos), `tenant_playbook` + `tenant_facts`, reporte semanal automatizado, lifecycle phases + comunicaciones, KB drop-zone, dashboard cliente 7 secciones MVP, dashboard super_admin con Home/Review Queue, landing (`apps/landing` + Aceternity UI), email outbound |
| **2** | Sprint Duet + Billing + UI pulida (6-8 sem) | Stripe Subscriptions + Tax + cupón FP, simulator auto-gen (personas + scenarios), bulk runner + scheduled nightly, **Diagnostic Tools** (Escalation Drivers + AOP Flow Analysis), **Watchtower** (rubrics custom), **AI Data Assistant cliente**, promotion gate robusto |
| **3** | Producción A/B + canary + escala (6-8 sem) | `agent_traffic_splits` por (tenant, AOP_version), production A/B con métricas comparativas, **canary deployment 5%→25%→50%→100%**, rollback automático, overage automation |

### Backlog futuro (Bloque 4, no asignado)

- Memory cross-conversación (deuda técnica, ver sección 19.2)
- Detección automática alucinaciones (refuerzo slow agent, ver sección 19.4)
- Reapertura conversaciones (`previous_conversation_id`)
- Voz/llamadas
- Intercom adapter (reactivo)
- WhatsApp directo via Twilio (solo si cliente sin helpdesk lo pide expresamente — caso edge)
- Modo proactivo / concierge (carritos abandonados, upsell)
- Embedding router pre-filtro al `select_aop`
- MCP server (skills as MCP)

---

## 17. Decisiones pendientes / TBD (todas resueltas al cierre del grill 2026-05-22)

- ~~**Authoring UX del AOP editor**~~ → resuelto Sprint 7: Markdown + YAML frontmatter en editor custom con preview. Sigue siendo el patrón.
- ~~**Política de retención de audit log**~~ → resuelto: 90 días hot, S3 cold después, hash original 180 días. Ver sección 11.3.
- ~~**Naming convention de skills**~~ → resuelto Sprint 6: `vendor.action` (`shopify.cancel_order`). Sigue siendo el patrón.
- ~~**`require_supervision` overrideable por tenant?**~~ → resuelto Sprint 8: sí, vía `tenant_configurations.extra` con bandera explícita.
- ~~**Evals**~~ → resuelto Sprint 7: obligatorio. Ver sección 9.
- ~~**PII hashing en app vs `pgcrypto`**~~ → resuelto Sprint 9.3: en app, salt por tenant en `tenant_secrets`.
- ~~**Esquema de roles en `intent_classifier_runs.human_correction`**~~ → resuelto: solo `super_admin` (Auyan). Cliente no toca esto en el modelo Managed.
- ~~**Cache invalidation tech**~~ → resuelto Sprint 9.4: Postgres LISTEN/NOTIFY (sin Redis).

### Decisiones NUEVAS del grill 2026-05-22 (todas resueltas)

Ver detalle en sección 20 abajo. Resumen:

- ~~**Modelo de entrega**~~ → producto Decagon/Sierra interno + entrega Crescendo cliente.
- ~~**KB del cliente**~~ → tres niveles (nunca/aporta/edita factual).
- ~~**Adapters por tenant**~~ → `MessageProvider` (base) + `HelpdeskProvider` (extends). Una abstracción unificada.
- ~~**Helpdesks en Bloque 0**~~ → 3 adapters: Gorgias + Chatwoot + Zendesk. Intercom reactivo (Bloque 4).
- ~~**Canales WhatsApp/Instagram/Widget**~~ → heredados via helpdesk, NO construidos directamente.
- ~~**Chatwoot self-hosted**~~ → descartado. Usamos Chatwoot Cloud; free/sandbox para verificación y paid si el cliente real lo necesita.
- ~~**Shadow mode**~~ → internal notes en helpdesk del cliente (modelo Sierra/Decagon).
- ~~**Activación gradual**~~ → por categoría, decisión Auyan no cliente.
- ~~**Onboarding**~~ → guiado por invitación (magic link), 9 pasos + call AIDE opcional.
- ~~**"Biblia" del cliente**~~ → tabla `tenant_playbook` en DB, NO Notion.
- ~~**Reporte semanal**~~ → email = resumen, dashboard = fuente completa, Kenny aprueba lunes 8am al inicio.
- ~~**Dashboard cliente**~~ → 7 secciones MVP, "Insights" reemplaza "Conversaciones", AI Data Assistant a Bloque 2.
- ~~**Dashboard super_admin**~~ → nav 2 niveles + Home Review Queue filtrado por rol.
- ~~**Roles internos**~~ → estructura DB desde día 1, ambos `super_admin` hasta mes 9-10.
- ~~**Simulator dimensiones del judge**~~ → 4 dims: Reasoning / Knowledge / Tools / Brand voice.
- ~~**Tipos de test**~~ → Unit / Integration / Simulation.
- ~~**AOPs steps[]**~~ → opcional preparado en Bloque 0 (data para Bloque 2 Flow Analysis).
- ~~**`tenant_agent`**~~ → hard removal en Bloque 0.
- ~~**Pricing/billing**~~ → motor de medición por resolución (`docs/billing-engine.md`); Stripe Bloque 2.
- ~~**Landing**~~ → `apps/landing` + Aceternity UI (no Tailwind UI).
- ~~**Design Sprint**~~ → 1-2 semanas al inicio de Bloque 1.

---

## 18. Anti-patrones explícitos (qué NO hacer)

- ❌ No poner `cancel_order` en el AOP `consulta_envio`. Cada AOP es estricto sobre sus skills.
- ❌ No dejar al LLM generar el `idempotency_key`. Lo genera el grafo.
- ❌ No editar `aop_versions` jamás — es append-only por diseño.
- ❌ No commitear AOPs en el repo. Viven en DB. (Los esqueletos seed sí pueden estar en `db/seeds/`.)
- ❌ No saltarse el supervisor en L3 "porque la confidence es alta". L3 SIEMPRE pasa por supervisor.
- ❌ No usar embeddings para clasificar intent en v1. LLM only hasta validar.
- ❌ No exponer audit log a `tenant_admin` sin scrubbing de PII de otros tenants (RLS).
- ❌ **No supervisar al supervisor.** Si el supervisor falla, se mejora offline con evals + cambios al prompt, NO encadenando otro supervisor en runtime. Madriguera infinita garantizada.
- ❌ **No correr el slow agent en todas las conversaciones desde el día 1.** Sampling primero, escalar cuando ROI esté validado.
- ❌ **No vender el "90% × 90% → 99%"** ni internamente. Es matemática falsa con errores correlacionados. Mide el delta real y reporta eso.
- ❌ **No poner tono específico de tenant dentro de un AOP.** Va en `tenant_config.agent_voice`. Los AOPs describen QUÉ hacer, no cómo suena.
- ❌ **No reclasificar el AOP en cada turno** sin razón. Destruye contexto. Lock por turnos cuando el flujo lo requiere.
- ❌ **No promover un AOP a `production` sin pasar evals.** El botón debe estar deshabilitado si falta cualquier fixture del inventario mínimo.
- ❌ **No reintentar tras `reject_kind=structural`**. Es desperdicio de tokens y latencia. Estructural = escalar directo.

---

---

## 19. Context Engineering — análisis de gaps (sesión 19, 2026-05-18)

Referencia: artículo de Neil Rahilly (Sierra) — "Context engineering: the key to great agents".

### 19.1 Qué está bien implementado

| Bloque Sierra | Nuestra implementación |
|---|---|
| Journey | AOPs con intent classifier (select_aop) |
| Tool | Skills L1/L2/L3 con allowed_skills por AOP |
| Rule/Policy | guardrails en YAML frontmatter del AOP |
| Workflow | cuerpo Markdown del AOP |
| Knowledge | RAG con pgvector (retrieve_knowledge) |
| Memory (parcial) | conversation_history 20 msgs + end_customer |

Progressive disclosure: el grafo carga contexto en 5 etapas secuenciales, cada nodo agrega solo lo suyo. El AgentState es aditivo (TypedDict total=False). La degradación es elegante: sin AOP → fallback a tenant_prompt; sin KB → agente igual opera.

### 19.2 Gaps identificados (priorizados)

**Alta prioridad:**

1. **Memory cross-conversación** — cargamos los últimos 20 mensajes de la conversación _actual_. Sierra define Memory como historial de conversaciones anteriores del mismo cliente + preferencias persistidas. Si un cliente ya contactó la semana pasada con el mismo problema, el agente no lo sabe. Fix: al cargar `end_customer`, buscar últimas N conversaciones resueltas del mismo `end_customer_id` e incluir un resumen.

2. **Glossary block ausente** — no existe bloque dedicado para terminología de la marca (nombres de productos, tiers de plan, jergón interno). Actualmente esa info puede estar en el body del AOP o en KB, mezclada con el resto. Fix: agregar campo `glossary` al YAML frontmatter del AOP y bloque `_render_glossary()` en el compiler.

**Media prioridad:**

3. **Condiciones por observación mid-turno** — `select_aop` clasifica el intent una vez al inicio (o en debloqueo). No hay re-evaluación continua si el cliente cambia de tema a mitad de conversación. Sierra usa "observation-based conditions" que disparan nuevo contexto en cualquier turno. Fix: en el nodo `reason`, detectar señales críticas mid-turno (keywords de cancelación, frustración, cambio de tema) e inyectar contexto adicional sin cambiar el AOP.

4. **Brand voice no es composable por AOP** — vive en `tenant_config.agent_voice` como string plano. No hay override por AOP (el AOP de reclamos debería sonar más formal que el de ventas). Fix: agregar `voice_override` en YAML frontmatter del AOP; el compiler prioriza `aop.voice_override` sobre `tenant_config.agent_voice`.

**Baja prioridad:**

5. **KB re-retrieval mid-ReAct loop** — los chunks se buscan una vez al entrar al nodo `retrieve_knowledge`, con el mensaje inbound. Si el agente hace preguntas y el cliente responde con info nueva que abre un sub-tema, el KB no se re-consulta con ese contexto. Fix: en `reason`, cuando `tool_iterations > 0` y hay nueva información relevante, hacer un segundo RAG pass.

6. **Tool exposure completo en cada turno** — si un AOP tiene 15 skills, las 15 se pasan a Claude en cada iteración del ReAct loop aunque solo 3 sean relevantes a la pregunta. A escala (1000 usuarios × 15 tools × N iteraciones) el token bleeding es significativo. Fix futuro: selección condicional de tools basada en el sub-tema activo.

7. **Context blocks no son primera clase** — los bloques de prompt son funciones en compiler.py (`_render_*`) sin metadata (condición de activación, prioridad, versión). Dificulta testing individual y extensión. Fix: clase `ContextBlock` con `condition`, `priority`, `render()`. No urgente hasta Sprint 13+.

### 19.3 Anti-patrones adicionales (de este análisis)

Ver también sección 18.

- ❌ **No asumir que "progressive disclosure" = "nodos secuenciales"**. La verdadera progressive disclosure es condicional en runtime. Nuestros nodos corren siempre; la condicionalidad la añadimos con el AOP locking y la ausencia de degradación. Es un primer paso válido, no el destino.
- ❌ **No mezclar glossary dentro del body del AOP**. Cuando el AOP explique el procedimiento y a la vez defina términos, Claude tiene que desambiguar qué es instrucción y qué es glosario. Van en bloques separados.
- ❌ **No confundir Memory (cross-conversación) con historial (conversación actual)**. Son bloques distintos. El historial ya funciona. Memory es trabajo futuro.

### 19.4 Detección de alucinaciones (estado actual y roadmap)

Estado actual: **no hay detección automática**. En 0.11A la revisión manual debe hacerse principalmente en LangSmith comparando chunks recuperados, tool outputs y respuesta del agente; Langfuse queda como espejo secundario mientras exista. La emisión de `retrieved_chunks` en los reasoning events ayuda.

Roadmap:
- **Inmediato (manual):** KB con datos fantasiosos específicos (números impares, nombres únicos) donde cualquier desviación es obvia. Script `seed_kb.py` implementado en sesión 19.
- **Sprint 11 (Slow Agent):** LLM-as-judge que, para una muestra de conversaciones, verifica si la respuesta está fundamentada en los chunks recuperados. Emit un evento `hallucination_risk: high/low` en reasoning.
- **Sprint 13+:** Gate de promotion en el AOP eval harness que incluye fixtures de "no debe alucinar sobre X".

---

_Última actualización: 2026-05-18 (sesión 19 — análisis context engineering Sierra + gaps priorizados + detección de alucinaciones)_

---

## 20. Arquitectura post-pivot — decisiones técnicas del grill 2026-05-22

Esta sección documenta los cambios arquitectónicos que entran con el pivot a Managed AI Service. Sobrescribe partes anteriores donde aplique.

### 20.1 Patrón Adapter por tenant — refactor crítico Bloque 0

**Problema actual** (deuda silenciosa detectada en grill):

```python
# integrations/zendesk.py — patrón actual
class ZendeskClient:
    def __init__(self) -> None:
        self.subdomain = settings.zendesk_subdomain   # ← global
        self.token = settings.zendesk_api_token       # ← global

zendesk = ZendeskClient()  # ← singleton compartido entre tenants
```

Esto **rompe multi-tenancy real**: dos clientes con Zendesk distintos no pueden coexistir. Mismo problema en `shopify.py` y `chatwoot.py`. Violación de la regla de oro del CLAUDE.md.

**Solución — protocolos unificados:**

```python
# integrations/base.py (nuevo)
class IntegrationContext(BaseModel):
    tenant_id: UUID
    credentials: dict  # cargadas de tenant_integrations descifradas

class MessageProvider(Protocol):
    """Base: cualquier source de mensajes (helpdesk o canal directo)."""
    async def parse_inbound_webhook(payload) -> InboundMessage: ...
    async def send_outbound(ctx, conversation_ref, content, attachments) -> None: ...

class HelpdeskProvider(MessageProvider, Protocol):
    """Extends: helpdesks con tickets, internal notes, status."""
    async def add_internal_note(ctx, ticket_ref, content) -> None: ...
    async def assign_to_human(ctx, ticket_ref, reason) -> None: ...
    async def update_status(ctx, ticket_ref, status) -> None: ...
    async def push_escalation(ctx, conversation, reason, agent_context) -> ExternalTicketRef: ...
```

**Implementaciones MVP (Bloque 0):**
- `ZendeskAdapter(HelpdeskProvider)` — refactor del actual
- `ChatwootAdapter(HelpdeskProvider)` — refactor del actual
- `GorgiasAdapter(HelpdeskProvider)` — nuevo (prioridad alta: 40% top Shopify)
- `PostmarkEmailAdapter(MessageProvider)` — outbound Auyan→cliente (no customer-facing)
- `ShopifyAdapter(CommerceProvider)` — refactor del actual (otro protocolo aparte)

**Tabla nueva** `tenant_integrations`:

```sql
CREATE TABLE tenant_integrations (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             UUID NOT NULL REFERENCES tenants(id),
    kind                  TEXT NOT NULL,        -- 'helpdesk' | 'commerce' | 'channel' | 'llm'
    provider              TEXT NOT NULL,        -- 'zendesk' | 'gorgias' | 'shopify' | ...
    credentials_encrypted BYTEA NOT NULL,       -- cifrado app-level con salt por tenant
    config                JSONB NOT NULL DEFAULT '{}',  -- subdomain, base_url, scopes, etc
    is_active             BOOLEAN NOT NULL DEFAULT TRUE,
    is_primary_for_kind   BOOLEAN NOT NULL DEFAULT FALSE,  -- para escalation routing
    enabled_at            TIMESTAMPTZ,
    enabled_by            UUID,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at            TIMESTAMPTZ,
    UNIQUE (tenant_id, kind, provider) WHERE deleted_at IS NULL
);
```

**IntegrationRegistry** (paralelo al `SkillRegistry` existente): decorator-based registry de implementaciones por `(kind, provider)`.

**OAuth obligatorio para helpdesks (verificado en grill):**
- Shopify: OAuth Partner App (1 botón cliente)
- Gorgias: OAuth2 obligatorio para Apps Store
- Zendesk: OAuth Authorization Code (mandatorio desde abril 2026)
- Chatwoot: API key (no OAuth standard, aceptable)

### 20.2 Shadow mode via internal notes — modelo Sierra/Decagon

**Decisión:** durante onboarding semana 3, el agente NO responde al cliente final automáticamente. Genera drafts que se postean como **internal notes** en el helpdesk del cliente.

**Flujo:**

```
1. Ticket entra al helpdesk del cliente (Gorgias/Zendesk/Chatwoot)
2. Webhook → Auyan
3. Auyan corre el grafo completo, genera draft de respuesta
4. ¿En shadow mode para esta categoría?
   a. SÍ → adapter.add_internal_note(ticket_ref, "🤖 Auyan sugiere: [draft]\nConfidence: X%\nAOP: Y")
   b. NO (categoría activada) → adapter.send_outbound(ticket_ref, draft)
5. Equipo del cliente ve el ticket en su helpdesk:
   - Si internal note → responde manualmente (puede usar el draft tal cual, editarlo, o ignorar)
   - Si auto-response → ya está enviado
6. Auyan registra diff entre draft y respuesta final del equipo cliente
7. Slow agent detecta patrones de concordancia/discordancia → propone updates
8. Cuando una categoría supera threshold de concordancia → Auyan propone activar esa categoría (auto-response)
```

**Importante:** el cliente no opera prompts ni reglas, pero la activación automática requiere aprobación explícita del cliente. Auyan recomienda y ejecuta la activación gradual por categoría según métricas.

**Bloque 3** evoluciona a **canary deployment**: en lugar de "shadow puro → 100%", se hace ramp 5%→25%→50%→100% por categoría con métricas tiempo real.

### 20.3 Escalación al equipo del cliente

**Refactor de `escalations` table:** ya no es "asignación a agente humano interno de Auyan" (modelo BPO viejo). Ahora es "referencia externa al helpdesk del cliente".

```sql
ALTER TABLE escalations
  DROP COLUMN assigned_user_id,
  ADD COLUMN external_provider TEXT,           -- 'zendesk' | 'gorgias' | 'chatwoot' | 'email'
  ADD COLUMN external_ticket_ref TEXT,         -- ID del ticket en el helpdesk del cliente
  ADD COLUMN notified_at TIMESTAMPTZ,          -- cuándo se push-eó al helpdesk/email
  ADD COLUMN acknowledged_at TIMESTAMPTZ;      -- cuándo el equipo del cliente lo vio
```

**Estrategia mix por tenant** configurada en onboarding:
- **Default cuando hay helpdesk integrado**: `helpdesk_adapter.push_escalation()` crea/actualiza ticket con contexto completo + razón en internal note
- **Fallback sin helpdesk**: email a casilla `notif_email` del tenant vía `PostmarkEmailAdapter`
- **Opcionales**: Slack webhook, custom webhook (Bloque 2+)

### 20.4 KB del cliente — tres niveles

**Decisión clave para preservar "fully managed" sin romper velocidad:**

| Nivel | Quién | Qué | Storage |
|---|---|---|---|
| 🔴 Nunca toca | Solo Auyan (super_admin/qa_km) | Prompts, AOPs, contenido RAG, retrieval config | Tablas `aops`, `kb_chunks` con embeddings |
| 🟡 Aporta no edita | Cliente sube → Auyan cura | Documentos, URLs, políticas, descripciones y archivos textuales | `tenant_knowledge_submissions` (cola pending review) → procesado a `knowledge_base_documents`/`knowledge_base_chunks` |
| 🟢 Edita directo | Cliente form plano | `tenant_facts`: horarios, teléfono, dirección, links | Tabla nueva `tenant_facts` (NO entra al RAG) |

**`tenant_facts` se lee como contexto estructurado del agente** (no como retrieval). Update inmediato sin curación. Schema editable por vertical (`tenant_fact_schema` table).

**`tenant_playbook` (NUEVO)** — reemplaza la idea original de "Biblia en Notion":

```sql
CREATE TABLE tenant_playbook (
    id            UUID PRIMARY KEY,
    tenant_id     UUID NOT NULL,
    section       TEXT NOT NULL,  -- 'brand_voice' | 'categories' | 'escalation_rules' | 'operating_context' | 'glossary' | 'edge_cases' | 'kb_references'
    content       JSONB NOT NULL,
    version       INT NOT NULL DEFAULT 1,
    created_at    TIMESTAMPTZ,
    updated_at    TIMESTAMPTZ,
    deleted_at    TIMESTAMPTZ
);
CREATE TABLE tenant_playbook_versions (
    -- append-only history para auditoría y diff
    id          UUID PRIMARY KEY,
    playbook_id UUID,
    section     TEXT,
    content     JSONB,
    version     INT,
    changed_by  UUID,
    changed_at  TIMESTAMPTZ
);
```

Visible solo en dashboard super_admin. Versionado, diffeable, RLS por tenant.

### 20.5 Simulator — 4 dimensiones del LLM-as-judge

Alineado con Sierra (Reasoning / Knowledge / Tools / Brand voice):

```python
class SimulationJudgment(BaseModel):
    reasoning_score: float       # 0-10: ¿siguió el AOP correctamente?
    knowledge_score: float       # 0-10: ¿info factualmente correcta sin alucinar?
    tools_score: float           # 0-10: ¿llamó skills correctas con inputs correctos?
    brand_voice_score: float     # 0-10: ¿mantuvo tono y guardrails?
    passed: bool                 # umbral configurable por tenant
    rationale: dict[str, str]    # razón por dimensión
```

**Tablas nuevas Bloque 0:**

```sql
CREATE TABLE user_profiles (
    id              UUID PRIMARY KEY,
    tenant_id       UUID,  -- NULL = template global
    name            TEXT,
    persona         JSONB,  -- {language, tone, tech_comfort, age_range, role}
    goal            TEXT,
    initial_message TEXT,
    follow_up_strategy TEXT,  -- "se frustra si toma >3 turnos"
    metadata        JSONB
);

CREATE TABLE simulation_scenarios (
    id              UUID PRIMARY KEY,
    tenant_id       UUID,
    aop_slug        TEXT,
    user_profile_id UUID,
    expected_outcome TEXT,  -- 'respond' | 'escalate' | 'ask_clarification'
    expected_skills JSONB,
    assertions      JSONB,
    is_active       BOOLEAN DEFAULT TRUE
);

CREATE TABLE simulation_runs (
    id              UUID PRIMARY KEY,
    tenant_id       UUID,
    scenario_id     UUID,
    aop_version     INT,
    status          TEXT,  -- 'running' | 'passed' | 'failed' | 'errored'
    transcript      JSONB,
    reasoning_events JSONB,
    judge_eval      JSONB,  -- SimulationJudgment serializado
    tokens_used     INT,
    cost_cents      NUMERIC,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ
);
```

**Bloque 0 — MVP del simulator:**
- `simulator/user_simulator.py` — LLM bot-cliente que responde turno por turno actuando como persona
- `simulator/runner.py` — multi-turn loop user_simulator ↔ agente real
- `simulator/judge.py` — LLM-as-judge con 4 dimensiones (reusa infra del slow agent Sprint 11)
- `routers/simulations.py` — API CRUD scenarios + run + bulk run
- UI super_admin: seleccionar scenarios, ejecutar, ver transcript + reasoning + judge feedback

**Bloque 2 — Simulator completo:**
- Auto-gen de personas desde AOP (LLM lee AOP → propone 10 personas variables)
- Auto-gen de scenarios desde AOPs + KB + transcripts históricos del cliente
- Bulk runner masivo (paralelo, 100s sims/run)
- Scheduled nightly regressions
- Templates de scenarios pre-construidos
- Diagnostic Tools (Escalation Drivers + AOP Flow Analysis)
- Watchtower (custom rubrics per tenant + scoring continuo conversaciones reales)
- Promotion gate: AOP no se promueve hasta pasar unit + integration + sims + rubrics threshold

**Bloque 3 — Production canary:**

```sql
CREATE TABLE agent_traffic_splits (
    id                   UUID PRIMARY KEY,
    tenant_id            UUID,
    aop_slug             TEXT,
    auto_respond_percentage INT,  -- 0-100, qué % va a auto-respond vs shadow
    rollback_thresholds  JSONB,   -- {min_csat: 4.0, max_error_rate: 0.05}
    set_at               TIMESTAMPTZ,
    set_by               UUID
);
```

El nodo `respond` lee `traffic_splits` por (tenant, aop) y decide aleatoriamente bucket: auto-respond → `send_outbound`; shadow → `add_internal_note`.

### 20.6 AOPs con `steps[]` opcional — preparación Bloque 0

Para habilitar **AOP Flow Analysis** estilo Decagon en Bloque 2 (drop-off por step), agregar campo opcional al schema YAML del AOP:

```yaml
---
slug: consulta_envio
allowed_skills: [shopify.get_order_by_email, shopify.get_order_by_number]
steps:
  - id: gather_identity
    name: "Solicitar identificación"
    decision_point: true
  - id: lookup_order
    name: "Buscar pedido en Shopify"
    decision_point: true
  - id: deliver_status
    name: "Comunicar estado al cliente"
    decision_point: false
---

## Procedimiento
[body markdown referencia los step IDs]
```

**Eventos a emitir** desde el grafo (extiende `agent_reasoning_events` Sprint 8):
- `step_entered(step_id, aop_version)`
- `step_completed(step_id, outcome)` — `outcome ∈ {progressed, looped, abandoned}`

Costo Bloque 0: medio día (campo opcional + emisión de eventos). Bloque 2 construye el dashboard de Flow Analysis sobre datos acumulados.

### 20.7 Roles internos — estructura DB desde día 1

```sql
CREATE TABLE internal_users (
    id            UUID PRIMARY KEY,
    auth_user_id  UUID UNIQUE,  -- referencia a Supabase Auth (separado de users tabla cliente-facing)
    name          TEXT,
    email         TEXT UNIQUE,
    role          internal_role NOT NULL,  -- enum: super_admin, aide, qa_km, ops_manager, cs_manager
    is_active     BOOLEAN DEFAULT TRUE,
    created_at    TIMESTAMPTZ,
    deleted_at    TIMESTAMPTZ
);

CREATE TYPE internal_role AS ENUM (
    'super_admin',  -- Kenny + esposa hasta mes 9-10
    'aide',
    'qa_km',
    'ops_manager',
    'cs_manager'
);

CREATE TABLE tenant_assignments (
    id                UUID PRIMARY KEY,
    tenant_id         UUID NOT NULL,
    internal_user_id  UUID NOT NULL,
    role_in_tenant    TEXT NOT NULL,  -- 'aide_primary' | 'aide_backup' | 'qa_assigned' | etc
    assigned_at       TIMESTAMPTZ,
    assigned_by       UUID,
    unassigned_at     TIMESTAMPTZ,
    UNIQUE (tenant_id, internal_user_id, role_in_tenant) WHERE unassigned_at IS NULL
);

CREATE TABLE role_permissions (
    role        internal_role,
    permission  TEXT,  -- 'aop.edit', 'integration.connect', 'approval.l3', etc
    PRIMARY KEY (role, permission)
);
```

Al inicio: solo Kenny + esposa con role `super_admin`. **Estructura lista para formalizar roles cuando contraten en mes 10-12** sin refactor de auth.

**Home/Review Queue del dashboard super_admin** se filtra por rol del usuario logueado vía joins con `tenant_assignments`. Mismo componente React, distinto resultset.

### 20.8 Hard removal de `tenant_agent` — Bloque 0

```sql
-- Migration atómica
UPDATE users SET role = 'tenant_admin' WHERE role = 'tenant_agent';

CREATE TYPE user_role_new AS ENUM ('super_admin', 'tenant_admin');
ALTER TABLE users ALTER COLUMN role DROP DEFAULT;
ALTER TABLE users ALTER COLUMN role TYPE user_role_new USING role::text::user_role_new;
DROP TYPE user_role;
ALTER TYPE user_role_new RENAME TO user_role;
ALTER TABLE users ALTER COLUMN role SET DEFAULT 'tenant_admin';
```

Código a actualizar:
- `apps/api/db/models.py`: `UserRole = Literal["super_admin", "tenant_admin"]`
- `apps/api/core/security.py`: actualizar docs + verificar lógica
- `apps/api/tests/test_security.py` + `test_metrics.py` + `test_escalations.py`: ~30 referencias, **revisar intent de cada test** (no search-and-replace)
- `apps/web/app/(dashboard)/page.tsx`: comentario
- `CLAUDE.md`: si menciona `tenant_agent`

### 20.9 Dashboard cliente — 7 secciones MVP

| Sección | Contenido | Bloque |
|---|---|---|
| **Home** | KPIs + lifecycle phase + heatmap + headline reporte semana + alertas | 1 |
| **Insights** (reemplaza "Conversaciones") | Heatmap timeline, donut intents, filtros, drill-down con reasoning panel | 1 |
| **Reportes** | Historial + reporte actual con sección narrativa LLM | 1 |
| **Knowledge Base** | Drop-zone + tenant_facts + estado procesamiento | 1 |
| **Aprobaciones** | Cola L3 pending (ya existe Sprint 10) | ✅ |
| **Onboarding** | Visible solo durante fase initial, auto-hide después | 1 |
| **Configuración** | Integraciones conectadas (status, no edit credentials) + branding + perfil AIDE | 1 |
| **AI Data Assistant cliente** | Chat conversacional NL sobre métricas (Duet for customers) | 2 |
| **Facturación** | Plan + tickets usados + factura próxima + historial PDFs | 2 |

**Stack:** shadcn + componentes chart existentes + sidebar ChatGPT/Claude-style.

### 20.10 Iteración rápida — qué va a DB editable

Principio transversal cerrado en grill:

| Pieza | Decisión |
|---|---|
| Pasos del wizard onboarding | Hardcoded (PR + redeploy aceptable) |
| **Preguntas cuestionario brand voice** | **DB editable** (`brand_voice_questions`) |
| **`tenant_facts` schema por vertical** | **DB editable** (`tenant_fact_schema`) |
| AOPs | ✅ DB con workspaces (Sprint 7) |
| Tool permissions | ✅ DB granular (Sprint 10) |
| **Notification templates (emails)** | **DB editable** (`notification_templates`) |
| **Report templates (Jinja)** | **DB editable** (`report_templates`) |
| Prompts del agente | ✅ Compilados desde AOPs |
| Adapter registry | Code-side |
| Feature flags por tenant | **DB editable** (`tenant_features`) |
| **Watchtower rubrics custom** | **DB editable** (Bloque 2) |
| Lifecycle phases (qué fases existen) | Hardcoded |

**Regla de oro:** lo que itera con cliente → DB editable. Lo que itera con código → code-side.

### 20.11 Privacidad y seguridad — refuerzos

| Área | Medida | Estado |
|---|---|---|
| Credentials integraciones | `credentials_encrypted` BYTEA con salt por tenant (NO env var global) | Bloque 0 |
| Uploads cliente (KB drop-zone) | `tenant_knowledge_submissions` con texto/URL/archivo textual client-side; Supabase Storage/PDFs quedan posterior | Bloque 1 completado |
| PII pseudonimización | ✅ Sprint 9.3 | OK |
| Cross-tenant access | Solo `super_admin` con MFA obligatorio + audit log de accesos cross-tenant | Refuerzo Bloque 0 |
| Trazas de observabilidad | Staging usa LangSmith como fuente primaria y puede trazar datos test/autorizados completos; producción requiere redacción/retención formal antes de activar | 0.11A staging |
| GDPR DPA | Firma digital en onboarding paso 7 | Bloque 1 |
| Right to erasure | Endpoint `DELETE /tenants/me/data` + cron purga real 30d | Bloque 1 |
| Servidores | EU (Supabase EU, Railway EU, Postmark EU) | ✅ ya configurado |

---

_Última actualización: 2026-05-22 (grill-me — pivot BPO → Managed AI service + arquitectura Bloques 0-3)_
