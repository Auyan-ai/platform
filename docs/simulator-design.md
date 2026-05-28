# Simulator MVP — Documento de diseño (Sub-PR 0.10)

> Diseñado y aprobado 2026-05-24. Modelo original: Opus 4.7 para judge.
> Estado 2026-05-28: implementado como base del Bloque 0.10; las decisiones operativas vigentes de coste/evals viven en `docs/progress.md`.
> Nota 0.11A: Sonnet 4.6 es el judge por defecto; Opus queda como calibración opcional y explícita.

---

## 0. Filosofía de diseño

Decagon y Sierra resolvieron tres problemas que tenemos que resolver también:

1. **Reproducibilidad** — el mismo scenario debe poder correrse 100 veces contra distintas versiones del AOP y producir resultados comparables.
2. **Señal accionable** — el output no es "pass/fail", es "el agente no llamó `get_order_status` cuando el cliente dio el #1234 en el turno 2". El judge da diagnósticos, no calificaciones.
3. **Volumen barato** — correr 100 simulaciones tiene que costar dólares, no decenas. Fuerza Haiku para el user_simulator y un solo paso de judge.

El sistema se construye alrededor de estos tres principios.

---

## 1. Resumen ejecutivo + decisiones clave

> **Nota de implementación (2026-05-25):** al implementar se descubrió que el grafo
> **no hace I/O externo** — los nodos `respond`/`escalate` solo persisten en DB y el
> envío al helpdesk + cierre de observabilidad los hace el **caller** (`AgentService`)
> post-grafo. Por eso `simulation_mode` solo se usa en `execute_skill` (inyección del
> mock). NO se tocan respond/escalate/finalize_trace. El runner simplemente no invoca
> el envío post-grafo. Además: fixtures indexadas por **nombre de método del adapter**
> (no skill slug), `commerce_mock: Any`, y conversaciones sintéticas con `channel='chat'`
> (el enum `channel_type` no tiene `'simulator'`) + `is_simulation=TRUE`.

| # | Decisión | Por qué |
|---|---|---|
| D1 | `simulation_mode: bool` en `AgentState`; solo `execute_skill` lo lee para inyectar el mock | El grafo no hace I/O externo, así que con interceptar el mock de commerce basta |
| D2 | Mock de Shopify vía `SkillContext.commerce_mock` inyectado por `execute_skill` desde fixtures del scenario | Type-safe (`CommerceProvider`), no monkey-patching, async-safe, 1 línea por skill |
| D3 | Conversación sintética persiste en `conversations` con `is_simulation=TRUE` | Reusa toda la infra del grafo (load_conversation, audit_log, reasoning_events); soft-delete al terminar |
| D4 | user_simulator usa Haiku 4.5 con prompt fijo + persona JSONB | Coste 10x menor que Sonnet; basta con coherencia, no inteligencia |
| D5 | Judge configurable: Sonnet 4.6 por defecto, Opus opcional para calibración puntual | Mantiene señal suficiente sin romper el tope normal de coste |
| D6 | Assertions programáticas (deterministas) + judge LLM (cualitativo) corren en paralelo | Las assertions atrapan el 70% de regresiones sin costo de LLM |
| D7 | Scenarios como código Python en `simulator/scenarios/` + seed a DB | Code review + git history desde día 1; UI de autoría es Bloque 2 |
| D8 | Bulk runs en paralelo limitado por semáforo PROCESS-wide (`Semaphore(10)`) | Aísla a 10 tenants concurrentes sin saturar Anthropic API ni DB pool |
| D9 | `tenant_id` NOT NULL en todas las tablas del simulador, seed copia scenarios por tenant | Elimina manejo de NULL; aislamiento por tenant_id + RLS es por construcción |
| D10 | Prompt caching de Anthropic en system prompts fijos | Reduce ~30% el costo del simulator/judge |

---

## 2. Cómo conectar `user_simulator` ↔ grafo real sin tocar el helpdesk

Decisión arquitectónica más importante. Durante el diseño se consideró interceptar nodos de salida; durante implementación se comprobó que no hacía falta porque el grafo no envía mensajes externos por sí mismo.

| Opción | Pros | Contras |
|---|---|---|
| A. Rebuild graph sin nodos respond/escalate | Cero side-effects | Duplica lógica; el grafo deja de ser "el agente real" |
| B. Mock del HelpdeskProvider en deps | Limpio en concepto | El adapter se resuelve dentro del nodo desde `tenant_integrations`, no desde deps. Requiere registrar adapter falso en DB |
| **C. Flag `simulation_mode` en `AgentState` + mock solo en `execute_skill`** | El grafo real se mantiene; intercepta únicamente I/O de commerce | Requiere que las skills acepten `commerce_mock` |

**Elegimos C, con implementación más pequeña que el diseño inicial.** `simulation_mode` existe en `AgentState`, pero solo lo lee `execute_skill` para inyectar `MockShopifyAdapter` en `SkillContext.commerce_mock`. Los nodos `respond`, `escalate` y `finalize_trace` quedan intactos: persisten estado interno, no hacen I/O externo al helpdesk, y el envío real lo hace `AgentService` fuera del grafo.

**Diff total en producción**:

```python
# agents/state.py
simulation_mode: bool
simulation_fixtures: dict  # fixtures por nombre de método del adapter

# skills/base.py
commerce_mock: Any | None

# agents/nodes/execute_skill.py
if state.get("simulation_mode"):
    commerce_mock = MockShopifyAdapter(fixtures)

# skills/shopify/*.py
adapter = ctx.commerce_mock or ShopifyAdapter()
```

**No se tocan `respond`, `escalate` ni `finalize_trace`.** Esta es la corrección importante frente al diseño inicial. Si una simulación falla raro, el debugging sale de `simulation_runs`, `messages`, `skill_audit_log` y `agent_reasoning_events`; el runner no dispara el envío post-grafo al helpdesk.

---

## 3. `user_simulator.py` — arquitectura

### Modelo y prompt

**Haiku 4.5 con temperature=0.7.** El simulador no necesita ser brillante — necesita ser coherente con su persona. Temperatura moderada para que dos runs no produzcan mensajes idénticos.

```
SYSTEM:
Eres un cliente sintético probando un agente de IA de soporte de {tienda}.

TU PERSONA: {persona_json}
TU IDIOMA: {language}
TU OBJETIVO: {goal}
ABANDONAS DESPUÉS DE: {give_up_after} turnos sin progreso claro.

REGLAS DURAS:
1. Escribe COMO ESE CLIENTE. Si la persona dice "tono frustrado, corto", no escribas párrafos.
2. NUNCA reveles que eres sintético. NUNCA digas "como IA" o "como bot".
3. Si en tu último turno ya recibiste lo que pedías, marca goal_achieved=true.
4. Si el agente repite la misma pregunta sin avanzar, considera give_up.
5. NO inventes información que la persona no tiene. Si no sabes el #pedido, dilo.

OUTPUT — solo JSON, sin markdown:
{
  "message": "tu próximo mensaje",
  "goal_achieved": bool,
  "give_up": bool,
  "internal_reasoning": "una frase para debugging"
}
```

El `SYSTEM` prompt se marca con prompt caching de Anthropic — el bloque fijo se cachea entre turnos.

### Behavior dentro de la persona

El comportamiento del cliente (cuándo da info, cuándo se impacienta) vive en `persona.behavior` (texto libre que se inyecta al prompt). No hay enum cerrado de strategies. Esto da flexibilidad sin complejidad estructural.

Ejemplos de `persona.behavior`:
- `"Das información cuando te la piden. Eres paciente."`
- `"Si no hay solución en 2 turnos del agente, presionas con frustración."`
- `"No das número de pedido a menos que el agente lo pida explícitamente."`

### Loop-detection automático

Si el agente produce dos respuestas seguidas cuyos primeros 200 caracteres son **idénticos** (comparación `==`), el runner fuerza `give_up=True` independiente de lo que diga el LLM. Evita loops infinitos cuando el agente está atascado.

### Truncado de history

El simulator recibe **solo los últimos 5 turnos** del historial al construir su prompt. El historial completo no aporta valor (la persona no necesita "recordar" mucho contexto) y duplica el costo en conversaciones largas.

### Interface

```python
@dataclass(frozen=True)
class SimulatorTurn:
    message: str
    goal_achieved: bool
    give_up: bool
    internal_reasoning: str
    input_tokens: int
    output_tokens: int

class UserSimulator:
    def __init__(self, profile: UserProfile, anthropic: AsyncAnthropic): ...
    
    def first_message(self) -> SimulatorTurn:
        """Retorna profile.initial_message sin llamar al LLM."""
    
    async def next_turn(
        self,
        conversation_history: list[dict],  # se trunca a últimos 5
        turn_number: int,
    ) -> SimulatorTurn: ...
```

---

## 4. `runner.py` — máquina de estados

### Flujo completo

```
INIT:
  insert simulation_run(status='running')
  insert conversation(channel='simulator', is_simulation=TRUE)
  sim = UserSimulator(profile)
  fixtures = scenario.mock_fixtures

TURN 0:
  turn = sim.first_message()
  insert message(role='customer', content=turn.message)
  transcript.append(turn)

LOOP (turn_number = 1 .. max_turns):
  agent_state = {
    tenant_id, conversation_id,
    inbound_message_content = transcript[-1].message,
    simulation_mode = True,
    simulation_fixtures = fixtures,
    langfuse_trace_id = f"sim-{run_id}-t{turn_number}",
  }
  final_state = await graph.ainvoke(agent_state)
  
  agent_response = final_state["agent_response"]
  insert message(role='agent_ai', content=agent_response)
  transcript.append(agent_turn)
  
  if final_state["decision"] == "escalate":
    return finish(reason='escalated_by_agent')
  
  if last_two_agent_responses_identical(transcript):
    return finish(reason='agent_loop_detected')
  
  sim_turn = await sim.next_turn(history[-5:], turn_number)
  insert message(role='customer', content=sim_turn.message)
  transcript.append(sim_turn)
  
  if sim_turn.goal_achieved: return finish(reason='goal_achieved')
  if sim_turn.give_up:       return finish(reason='give_up')

return finish(reason='max_turns')

FINISH(reason):
  skill_log = list_skill_audit_log(conversation_id)
  
  assertions_results = check_assertions(transcript, skill_log, scenario.assertions)
  judge_verdict = await judge_simulation(transcript, skill_log, scenario)
  
  status = compute_status(assertions_results, judge_verdict)
  # 'passed'  si todas assertions críticas pasan Y judge.overall_score >= 7.5
  # 'partial' si al menos una assertion crítica pasa y judge >= 6
  # 'failed'  lo demás
  
  update simulation_run(status, transcript, judge_eval, ...)
  soft_delete conversation(is_simulation=TRUE)
```

### Estado mantenido

```python
@dataclass
class SimulationRunState:
    run_id: UUID
    scenario: SimulationScenario
    profile: UserProfile
    conversation_id: UUID
    transcript: list[TranscriptTurn]
    turn_number: int
    termination_reason: str | None
    final_agent_state: dict | None
    tokens_simulator_in: int
    tokens_simulator_out: int
    tokens_agent_in: int
    tokens_agent_out: int
```

### Defaults

- `max_turns` = 8 (override por scenario)
- `simulation_timeout_seconds` = 180 (run completo)
- `loop_detection_window` = 2 turnos
- `history_truncation` = 5 turnos (lo que ve el simulator)

### Concurrencia: semáforo PROCESS-wide

```python
# simulator/runner.py
_GLOBAL_SIM_SEMAPHORE = asyncio.Semaphore(10)

async def run_simulation(...):
    async with _GLOBAL_SIM_SEMAPHORE:
        ...
```

10 simulaciones concurrentes máximo en TODO el proceso. Si 10 tenants disparan batches simultáneos, se serializan. Cada simulación tarda ~30s, 10 secuenciales = 5 min. Aceptable.

Esto protege contra:
- **Anthropic rate limits**: 50 simulaciones × 5 turnos × 2 LLM calls = 500 calls/min. Con semaphore=10, máximo 100 calls/min, bajo el límite.
- **DB connection pool**: 10 simulaciones × ~3 conexiones = 30 conexiones, bajo el pool por default.

---

## 5. Sistema de mocks

### Tres opciones evaluadas

| Opción | Cambio en producción | Thread-safety | Trade-off |
|---|---|---|---|
| A. `unittest.mock.patch` global | 0 | ❌ no thread-safe | Solo tests serializados |
| B. ContextVar leído dentro de `ShopifyAdapter` | Adapter chequea ContextVar | ✅ por task | Lógica de mock contamina el adapter |
| **C. `SkillContext.commerce_mock` + 1 línea por skill** | 1 campo + 11 líneas | ✅ explícito | 11 archivos, cambio trivial cada uno |
| D. Mock al nivel HTTP (`respx`) | 0 | ✅ por task | Frágil ante cambios de endpoints |

**Elegimos C.** Cambio invasivo mínimo, contrato explícito y tipado.

### Implementación

```python
# skills/base.py — 1 campo nuevo
@dataclass(frozen=True)
class SkillContext:
    tenant_id: str
    conversation_id: str
    integration_ctx: IntegrationContext | None = None
    commerce_mock: CommerceProvider | None = None

# skills/shopify/get_order_status.py — 1 línea cambia
adapter = ctx.commerce_mock or ShopifyAdapter()

# agents/nodes/execute_skill.py — bloque nuevo
if state.get("simulation_mode"):
    fixtures = state.get("simulation_fixtures", {}).get("shopify", {})
    commerce_mock = MockShopifyAdapter(fixtures)
else:
    commerce_mock = None
skill_ctx = SkillContext(
    tenant_id=..., conversation_id=...,
    integration_ctx=..., commerce_mock=commerce_mock,
)
```

### `MockShopifyAdapter`

```python
@dataclass
class MockShopifyAdapter:
    fixtures: dict  # slug → response | {"_error": "ERROR_CODE"}
    
    def _get(self, slug: str):
        data = self.fixtures.get(slug)
        if data and "_error" in data:
            raise ShopifyAPIError(data["_error"])
        return data
    
    async def get_order_by_name(self, ctx, order_identifier):
        return self._get("shopify.get_order_status")
    async def search_orders_by_email(self, ctx, email):
        data = self._get("shopify.get_order_by_email")
        return [data] if data else []
    async def get_customer_by_email(self, ctx, email):
        return self._get("shopify.get_customer_history")
    # ... los 8 métodos restantes
```

**Fallback default**: si una skill llama un método cuyo fixture no está definido, el mock retorna `None` (= "no encontrado") en vez de explotar. Fácil de extender.

### Estructura del fixture

Indexada por **nombre de método del adapter** (no skill slug) — el mock opera a
nivel de método y una skill puede hacer varias llamadas:

```json
{
  "shopify": {
    "get_order_by_name": {
      "found": true,
      "order_number": "#1234",
      "fulfillments": [{"tracking_number": "1Z999...", "tracking_url": "..."}]
    },
    "search_orders_by_email": [{"id": 1, "name": "#1234"}],
    "get_customer_by_email": {"_error": "NOT_FOUND"}
  }
}
```

Métodos disponibles: `get_order`, `get_order_by_name`, `search_orders_by_email`,
`get_customer_by_email`, `get_orders_by_customer_id`, `search_products`,
`get_policies`, `add_order_note`, `tag_order`, `cancel_order`,
`update_shipping_address`, `refund_partial`, `start_return`.

Defaults sin fixture: lecturas-objeto → `None`, lecturas-lista → `[]`,
escrituras → `{"ok": true, "simulated": true}`. El `_error` fuerza al mock a lanzar
`MockShopifyError` — esencial para scenarios EX-* que prueban manejo de errores.

---

## 6. Judge: reuso del slow agent y diferencias

### Comparativa

| Aspecto | Slow Agent | Simulator |
|---|---|---|
| Input | Transcript real (sin expectativas) | Transcript sintético + `goal` + `expected_outcome` + `assertions` |
| Objetivo | "¿Hay que cambiar el AOP?" → propone diff | "¿Pasó este test?" → scores + diagnóstico |
| Output schema | `JudgeVerdict` (proposal_type, diff_markdown) | `SimulatorJudgeVerdict` (4 scores, assertions_results, suggestions) |
| Modelo | Sonnet → Opus (two-step) | **Sonnet por defecto; Opus opcional** |
| Volumen | ~50 conversations/semana/tenant | ~25 runs/batch, manual |

### Modelo actual del judge

La decisión original favorecía Opus para todos los juicios porque el volumen esperado era bajo. En 0.11A el foco cambió: necesitamos correr más veces en staging, comparar versiones y mantener una corrida normal bajo `$5`. Por eso el default es `claude-sonnet-4-6`; Opus se reserva para calibrar una muestra pequeña cuando la señal de Sonnet sea ambigua o cuando se quiera auditar un cambio de alto riesgo.

### Lo que se reutiliza

- Patrón `_call_judge()` con JSON parse + fallback (`slow_agent/judge.py:40-92`)
- `format_for_judge()` en `slow_agent/transcript.py` como base — extendido para incluir `goal`, `expected_outcome`, `assertions` y `simulator_turns_metadata`
- Patrón `RunStats` con cost tracking — adaptado a `SimulationStats`

### Lo que NO se reutiliza

- `JUDGE_SYSTEM_PROMPT` — improvement-focused, no aplica
- `JudgeVerdict` dataclass — schema diferente
- Two-step escalation

### Output

```python
@dataclass(frozen=True)
class SimulatorJudgeVerdict:
    # Scores 0-10 por dimensión
    reasoning_score: int
    knowledge_score: int
    tools_score: int
    brand_voice_score: int
    overall_score: float  # promedio simple
    
    verdict: Literal["pass", "partial", "fail"]
    
    # Explicaciones (1-2 frases cada una)
    reasoning_explanation: str
    knowledge_explanation: str
    tools_explanation: str
    brand_voice_explanation: str
    
    # Evaluación independiente del goal
    judge_goal_achieved: bool
    judge_goal_explanation: str
    
    # Sugerencia accionable para el AOP
    suggestions: str
    
    # Metadata
    model_used: str
    input_tokens: int
    output_tokens: int
```

### Optimización: skill_audit_log filtrado

El judge recibe el transcript completo PERO el skill_audit_log se filtra a solo skills ejecutadas (no audit completo de la tabla). Reduce tokens ~40% en scenarios con muchas skills.

### Prompt

`SIM_JUDGE_SYSTEM_PROMPT` se marca con prompt caching (bloque fijo, cacheable entre runs):

```
SYSTEM (cached):
Eres evaluador experto de agentes de IA de soporte. Tu trabajo es puntuar 
el desempeño en 4 dimensiones y emitir un veredicto.

DIMENSIONES (0-10 cada una):

1. REASONING — ¿Razonó correctamente sobre la situación?
   0-3: contradicciones o lógica defectuosa
   4-6: correcto pero mecánico
   7-9: sólido, contextual
   10: anticipa necesidades, maneja incertidumbre

2. KNOWLEDGE — ¿Información correcta y completa?
   PENALIZAR HALLUCINATION agresivamente: cualquier dato no soportado por KB o tool_output → score ≤ 4

3. TOOLS — ¿Tools correctas con inputs correctos?
   - Penalizar tools innecesarias
   - Penalizar NO llamar tools que debió llamar

4. BRAND VOICE — ¿Tono y estilo del AOP? ¿Adaptado a la persona del cliente?

EVALUACIÓN DE GOAL: independiente del simulador. Como evaluador externo, 
¿el cliente recibió lo que necesitaba?

SUGERENCIAS: 1-3 frases concretas sobre qué cambiar en el AOP.

CRITERIOS DE VEREDICTO:
- pass:    overall ≥ 7.5 Y judge_goal_achieved=true
- partial: overall ≥ 6.0 O (goal_achieved con problemas)
- fail:    overall < 6.0 O goal claramente no logrado

OUTPUT — solo JSON, sin markdown.

USER (per-call):
CONTEXTO:
- Goal del cliente: {goal}
- Outcome esperado: {expected_outcome}
- AOP que seguía el agente: {aop_compiled_prompt}

TRANSCRIPT:
{formatted_transcript}

SKILLS EJECUTADAS:
{filtered_skill_log}

ASSERTIONS PROGRAMÁTICAS (info, no calificar):
{assertions_results}
```

---

## 7. Assertions programáticas

Corren antes del judge. Si una crítica falla, el judge igual corre pero el status final será `failed` independiente del score.

```python
# simulator/assertions.py

@dataclass(frozen=True)
class AssertionResult:
    key: str
    passed: bool
    evidence: str
    is_critical: bool

def check_assertions(
    transcript: list[TranscriptTurn],
    skill_log: list[SkillAuditLog],
    assertions: dict,
) -> list[AssertionResult]: ...
```

### Tipos soportados (MVP)

| Key | Verifica | Crítica |
|---|---|---|
| `skills_called[]` | Cada slug aparece en skill_log con status='success' | ✅ |
| `skills_not_called[]` | Ningún slug aparece en skill_log | ✅ |
| `response_contains[]` | Substrings (case-insensitive) en último msg del agente | ❌ |
| `response_not_contains[]` | Substrings ausentes en último msg del agente | ✅ |
| `outcome_is` | 'resolved' | 'escalated' | 'abandoned' (mapeado desde termination_reason) | ✅ |
| `max_turns` | `turns_count <= N` | ❌ |
| `must_escalate` | bool | ✅ |
| `must_have_pending_approval` | El estado final tiene `pending_approval_id` (L3 gate) | ✅ |

---

## 8. Schema SQL final

```sql
-- 20260522000004_add_simulator_tables.sql

-- Marca para distinguir conversaciones sintéticas
ALTER TABLE conversations ADD COLUMN is_simulation BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX conversations_not_simulation ON conversations(tenant_id, created_at) 
    WHERE is_simulation = FALSE AND deleted_at IS NULL;
-- CRÍTICO: el slow_agent y todas las queries operacionales deben filtrar 
-- WHERE is_simulation = FALSE

CREATE TABLE user_profiles (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id),
    name                TEXT NOT NULL,
    persona             JSONB NOT NULL DEFAULT '{}',  -- tono, behavior, give_up_after
    goal                TEXT NOT NULL,
    initial_message     TEXT NOT NULL,
    language            TEXT NOT NULL DEFAULT 'es',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_profiles_isolation ON user_profiles
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

CREATE TABLE simulation_scenarios (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id),
    name                TEXT NOT NULL,
    description         TEXT,
    aop_slug            TEXT NOT NULL,
    user_profile_id     UUID NOT NULL REFERENCES user_profiles(id),
    expected_outcome    TEXT NOT NULL,
    mock_fixtures       JSONB NOT NULL DEFAULT '{}',
    assertions          JSONB NOT NULL DEFAULT '{}',
    max_turns           INT NOT NULL DEFAULT 8,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX sim_scenarios_aop_slug 
    ON simulation_scenarios(tenant_id, aop_slug) 
    WHERE is_active = TRUE;
ALTER TABLE simulation_scenarios ENABLE ROW LEVEL SECURITY;
CREATE POLICY sim_scenarios_isolation ON simulation_scenarios
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

CREATE TABLE simulation_runs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id),
    scenario_id         UUID REFERENCES simulation_scenarios(id),
    aop_slug            TEXT NOT NULL,
    aop_version         INT,
    conversation_id     UUID,
    batch_id            UUID,
    status              TEXT NOT NULL DEFAULT 'running',
                        -- running | passed | partial | failed | errored
    termination_reason  TEXT,
                        -- goal_achieved | max_turns | give_up | 
                        -- escalated_by_agent | agent_loop_detected | error
    turns_count         INT,
    transcript          JSONB,
    judge_eval          JSONB,
    assertions_results  JSONB,
    assertions_passed   INT,
    assertions_total    INT,
    triggered_by        UUID,
    tokens_simulator    INT DEFAULT 0,
    tokens_agent        INT DEFAULT 0,
    tokens_judge        INT DEFAULT 0,
    cost_cents          NUMERIC(10,4),
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ
);
CREATE INDEX sim_runs_scenario ON simulation_runs(scenario_id, started_at DESC);
CREATE INDEX sim_runs_batch ON simulation_runs(batch_id) WHERE batch_id IS NOT NULL;
CREATE INDEX sim_runs_running ON simulation_runs(status) WHERE status = 'running';
CREATE INDEX sim_runs_tenant_daily_cost 
    ON simulation_runs(tenant_id, started_at) 
    WHERE status IN ('passed', 'partial', 'failed', 'errored');
ALTER TABLE simulation_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY sim_runs_isolation ON simulation_runs
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
```

### Notas críticas

- **`tenant_id` NOT NULL** en las 3 tablas → simplifica queries, RLS funciona automático.
- **Seed por tenant**: el script de seed copia los 25 scenarios base a cada tenant nuevo. 25 × 10 tenants = 250 rows, trivial.
- **RLS habilitado** en las 3 tablas → defensa adicional contra cross-tenant leaks.
- **Índice `sim_runs_tenant_daily_cost`** sirve a la query de cost cap diario.
- **`is_simulation=TRUE` filter** debe agregarse a TODAS las queries operacionales de `conversations`. Auditar antes de mergear.

---

## 9. Estructura de archivos y interfaces públicas

```
apps/api/simulator/
├── __init__.py
├── user_simulator.py    → UserSimulator, SimulatorTurn
├── runner.py            → run_simulation(), run_batch(), _GLOBAL_SIM_SEMAPHORE
├── judge.py             → judge_simulation(), SimulatorJudgeVerdict
├── assertions.py        → check_assertions(), AssertionResult
├── mocks.py             → MockShopifyAdapter
├── transcript.py        → build_simulator_transcript(), format_for_sim_judge()
├── cost_guard.py        → check_tenant_cost_cap(), check_global_cost_cap()
├── prompts.py           → SIMULATOR_PROMPT, SIM_JUDGE_SYSTEM_PROMPT
└── scenarios/
    ├── __init__.py      → load_seed_scenarios()
    ├── profiles.py      → 4 personas base
    ├── consulta_envio.py → 8 scenarios CE-*
    ├── returns.py       → 7 scenarios RE-*
    ├── default.py       → 6 scenarios DE-*
    └── edge_cases.py    → 4 scenarios EX-*

apps/api/routers/
└── simulations.py       → REST API con gates de tenant_id
```

### Interfaces públicas

```python
# runner.py
async def run_simulation(
    scenario_id: UUID,
    tenant_id: UUID,
    triggered_by: UUID | None = None,
    *,
    deps: AgentDependencies,
    compiled_graph: CompiledStateGraph,
) -> UUID:  # retorna run_id
    ...

async def run_batch(
    scenario_ids: list[UUID],
    tenant_id: UUID,
    *,
    triggered_by: UUID | None = None,
) -> UUID:  # retorna batch_id
    ...

# judge.py
async def judge_simulation(
    anthropic: AsyncAnthropic,
    transcript: SimulatorTranscript,
    scenario: SimulationScenario,
) -> SimulatorJudgeVerdict: ...

# cost_guard.py
async def check_tenant_cost_cap(tenant_id: UUID) -> None:
    """Raises HTTPException(429) si tenant superó $10/día."""

async def check_global_cost_cap() -> None:
    """Raises HTTPException(429) si proceso superó $50/día."""
```

### REST API

Todos los endpoints aplican gates de tenant_id explícitos.

| Método | Endpoint | Gate de tenant | Rate limit |
|---|---|---|---|
| POST | `/simulations/scenarios` | scenario.tenant_id = user.tenant_id O super_admin | - |
| GET  | `/simulations/scenarios` | filtra por user.tenant_id (super_admin ve todos) | - |
| POST | `/simulations/runs` | scenario.tenant_id == user.tenant_id O super_admin | 20/h por tenant |
| POST | `/simulations/batches` | todos los scenarios pertenecen al tenant del user O super_admin | 5/h por tenant |
| GET  | `/simulations/runs/{run_id}` | run.tenant_id == user.tenant_id O super_admin | - |
| GET  | `/simulations/batches/{batch_id}` | batch.tenant_id == user.tenant_id O super_admin | - |
| GET  | `/simulations/scenarios/{id}/runs` | scenario.tenant_id == user.tenant_id O super_admin | - |

**Reglas de tenant_id**:
- `tenant_id` del run = `scenario.tenant_id` (source of truth, no el del usuario)
- Super_admin de Auyan operando para cliente X → run se atribuye a X
- Rate limits y cost caps se cuentan contra `scenario.tenant_id`

### Cost guards (en cost_guard.py)

```python
async def check_tenant_cost_cap(tenant_id: UUID) -> None:
    async with tenant_scope(tenant_id) as conn:
        total_cents = await conn.fetchval("""
            SELECT COALESCE(SUM(cost_cents), 0) 
            FROM simulation_runs 
            WHERE tenant_id = $1 
              AND started_at >= NOW() - INTERVAL '1 day'
        """, tenant_id)
        if total_cents > 1000:  # $10 = 1000 cents
            raise HTTPException(429, "tenant_daily_cost_cap_exceeded")

# Global cap usa Redis para contador in-memory
async def check_global_cost_cap() -> None:
    daily_cost = await redis.get("sim_global_cost_today_cents") or 0
    if daily_cost > 5000:  # $50 = 5000 cents
        raise HTTPException(429, "global_daily_cost_cap_exceeded")
```

Ambos checks corren ANTES de iniciar cada run.

---

## 10. Taxonomía de 25 scenarios

### Personas (4 arquetipos en `scenarios/profiles.py`)

```python
PERSONAS = {
    "cooperativo": {
        "tone": "amable y directo",
        "behavior": "Das información cuando te la piden. Eres paciente. Aceptas explicaciones razonables.",
        "give_up_after": 10,
    },
    "impaciente": {
        "tone": "frustrado, mensajes cortos",
        "behavior": "Si no hay solución en 2 turnos del agente, presionas con frustración. No elaboras mucho.",
        "give_up_after": 3,
    },
    "vago": {
        "tone": "confundido, información mínima",
        "behavior": "No das número de pedido a menos que el agente lo pida explícitamente. Respondes con mínima información.",
        "give_up_after": 8,
    },
    "abandona_pronto": {
        "tone": "desinteresado",
        "behavior": "Si no hay respuesta clara en 2 turnos del agente, desistes sin escalar.",
        "give_up_after": 2,
    },
}
```

### `consulta_envio` (8)

| ID | Persona | Goal | Assertions críticas |
|---|---|---|---|
| CE-01 | cooperativo | Tracking de #1234 (con tracking) | skills_called=[get_order_status]; response_contains=[tracking]; max_turns=2 |
| CE-02 | impaciente | Tracking de #1234 (sin fulfillment) | response_contains=[aún no]; no_escalate |
| CE-03 | vago | Estado de "mi último pedido" (da email) | skills_called=[get_order_by_email]; max_turns=3 |
| CE-04 | cooperativo | Tracking de #9999 (no existe) | response_contains=[no encontr]; skills_not_called=[cancel_order, refund_partial] |
| CE-05 | vago | "¿Cuándo llega?" (confunde fechas) | skills_called=[get_order_status]; judge.brand_voice ≥ 7 |
| CE-06 | impaciente | Cliente tiene 2 órdenes recientes | agent pregunta cuál; skills_called=[get_order_by_email] |
| CE-07 | cooperativo (en) | Get tracking in English | response in English; AOP language handling |
| CE-08 | cooperativo | Tracking + "¿puedo devolver?" al final | agent stays on consulta_envio; max_turns≤4 |

### `returns` (7)

| ID | Persona | Goal | Assertions críticas |
|---|---|---|---|
| RE-01 | cooperativo | Devolver #1234 (en plazo) | skills_called=[start_return]; outcome=resolved |
| RE-02 | cooperativo | Devolver #1234 (fuera de plazo) | response_contains=[política, 30 días]; skills_not_called=[start_return] |
| RE-03 | cooperativo | Reembolso por producto roto | skills_called=[refund_partial]; must_have_pending_approval=true (L3) |
| RE-04 | vago | Devolver sin factura | agent pide alternativas; judge.knowledge ≥ 7 |
| RE-05 | cooperativo | Devolver producto digital | response_contains=[no devolución digital]; skills_not_called=[start_return] |
| RE-06 | impaciente | Exige refund agresivamente | must_escalate; judge.brand_voice ≥ 7 |
| RE-07 | cooperativo | Inicia devolución, se arrepiente turno 3 | sin skills después de cancelación; outcome=resolved |

### `default` (6)

| ID | Persona | Goal | Assertions críticas |
|---|---|---|---|
| DE-01 | cooperativo | "¿Cuánto tarda el envío?" | response_contains=[días]; skills_not_called=[get_order_status]; judge.knowledge ≥ 8 |
| DE-02 | cooperativo | "¿Qué garantía tiene producto X?" | answered from KB; max_turns=2 |
| DE-03 | cooperativo | Pregunta fuera de alcance | must_escalate; response_not_contains=[información inventada] |
| DE-04 | cooperativo | Cambiar dirección antes de envío | skills_called=[update_shipping_address]; supervisor activado |
| DE-05 | cooperativo | "¿Tienen talla M?" | skills_called=[get_product_info] |
| DE-06 | abandona_pronto | (solo "hola") | agent pregunta clarificadora; no skills; outcome=abandoned |

### Edge cases (4)

| ID | Persona | Goal | Assertions críticas |
|---|---|---|---|
| EX-01 | cooperativo | Tracking pero mock retorna `_error` | response_not_contains=[error interno]; must_escalate |
| EX-02 | cooperativo | Pregunta sin respuesta en KB | judge.knowledge ≥ 7; must_escalate |
| EX-03 | vago | Nunca da info (max_turns) | termination=max_turns; outcome=escalated |
| EX-04 | cooperativo | Cancelar pedido pagado (L3) | skills_called=[cancel_order]; must_have_pending_approval |

**Total: 25 scenarios. 4 personas reutilizadas en múltiples scenarios.**

---

## 11. Aislamiento multi-tenant — auditoría

Defensa en profundidad. Cada layer protege contra una clase de fallo:

| Capa | Mecanismo | Protege contra |
|---|---|---|
| 1. REST API | Gates explícitos `scenario.tenant_id == user.tenant_id O super_admin` | Tenant A no puede llamar endpoints contra recursos de tenant B |
| 2. DB Schema | `tenant_id NOT NULL` + FK + RLS policies | Inserts y selects siempre respetan boundary aunque alguien olvide el filtro |
| 3. Graph runtime | `tenant_scope(tenant_id)` setea `app.current_tenant_id` | Toda query dentro del grafo aplica RLS automático |
| 4. Mocks | `commerce_mock` viene de `scenario.mock_fixtures` con scenario.tenant_id validado | Mock no puede leakear datos de otro tenant porque viene del propio scenario |
| 5. Simulación de conversación | `conversation.tenant_id = scenario.tenant_id`, `is_simulation=TRUE` | Conversación sintética nunca se mezcla con producción ni cross-tenant |

**Riesgo residual cero** si la capa 1 (REST gates) se implementa correctamente. RLS lo protege como fallback.

---

## 12. Cost guardrails — auditoría

| Capa | Límite | Acción |
|---|---|---|
| Per-tenant rate limit | 5 batches/h, 20 runs/h | HTTP 429 al endpoint |
| Per-run budget recomendado | $5 por corrida normal | CLI/runner corta antes de iniciar runs que excedan presupuesto estimado |
| Per-tenant daily cost cap | $10/día | HTTP 429 antes de iniciar run |
| Global daily cost cap | $50/día across all tenants | HTTP 429 + alerta a super_admin |
| Process semaphore | 10 concurrent simulations | Cliente espera, no falla |

**Optimizaciones que reducen costo base ~40%**:
- Prompt caching de Anthropic en `SIMULATOR_PROMPT` y `SIM_JUDGE_SYSTEM_PROMPT` (system fijo, cacheable)
- `user_simulator` recibe solo últimos 5 turnos del history
- Judge recibe skill_audit_log filtrado a solo skills llamadas

**Costo operativo actual**:

| Corrida | Judge | Objetivo |
|---|---|
| Smoke CE-01 + RE-01 | No | Validar que grafo, fixtures y assertions críticas siguen sanas. |
| 25 scenarios completos | No | Regresión barata; debe pasar critical assertions. |
| Sample 8 scenarios | Sonnet 4.6 | Evaluación cualitativa normal; promedio mínimo `8/10`. |
| Calibración puntual | Opus | Solo manual, sobre muestra pequeña y con razón explícita. |

La proyección mensual debe recalcularse con `apps/api/integrations/pricing.py`; no duplicar precios hardcoded dentro del runner.

Sustentable.

---

## 13. Riesgos

| # | Riesgo | Severidad | Mitigación |
|---|---|---|---|
| R1 | `is_simulation=TRUE` no se filtra en queries existentes → slow_agent procesa conversaciones sintéticas | **Alta** | Auditar TODAS las queries de conversations. Test que verifica que slow_agent y métricas filtran `is_simulation=FALSE`. |
| R2 | `select_aop` rotea a un AOP distinto del esperado | Media | Trackear `aop_slug` activo en cada turn; el judge recibe esto y puede comentar |
| R3 | user_simulator marca goal_achieved prematuramente | Baja | Diseño absorbe: judge evalúa goal independientemente; veredicto final usa judge |
| R4 | Mocks faltan métodos cuando se agregan skills nuevas | Baja | MockShopifyAdapter retorna `None` por default; fácil extender |
| R5 | Anthropic rate limit en batches concurrentes | Media | `_GLOBAL_SIM_SEMAPHORE(10)` + backoff exponencial en 429 |
| R6 | Determinismo: dos runs del mismo scenario dan resultados distintos | Media | Pinear `temperature=0` para el agente en simulation_mode. Aceptable porque simulator (Haiku) tiene 0.7. |
| R7 | Ruido de observabilidad: 125 trazas/batch contaminan dashboards | Media | Tag `simulation=true`; LangSmith como fuente primaria de evals, Langfuse como espejo secundario existente |
| R8 | Costo runaway por loop accidental de "Run all" | Baja | 3 capas de cost guards (rate limit + per-tenant cap + global cap) |

---

## 14. Decisiones abiertas (resueltas)

| # | Decisión | Resolución |
|---|---|---|
| D11 | Bulk run sync o async | **Async + polling**. Single run sync con timeout 60s |
| D12 | Scenarios en código o DB | **Código + seed**. UI de autoría en Bloque 2 |
| D13 | Comparar runs de dos AOP versions side-by-side | **MVP solo lista de runs por scenario**. Comparación visual en Bloque 2 |
| D14 | `judge_eval` propone diffs de AOP automáticos | **No**. Solo `suggestions: str` libre. Auto-propuesta en Bloque 2 |
| D15 | Tenant real o "simulation tenant" | **Tenant real + `is_simulation`**. Sin duplicación de setup |
| D16 | Probar approval gates de L3 simulando aprobación | **No**. Verificar que `pending_approval_id` se setea. El gate ES lo que se prueba. |
| D17 | Temperature del agente en simulation_mode | **Pinear a 0** para reproducibilidad |
| D18 | Persistir `agent_reasoning_events` en simulaciones | **Sí, normal en la tabla**. Filtrado por `is_simulation` cuando se consume |

---

## 15. Lo que NO se hace en MVP (alcance explícito)

- ❌ UI de autoría de scenarios (Bloque 2)
- ❌ Comparación side-by-side de AOP versions (Bloque 2)
- ❌ Auto-propuesta de diffs de AOP desde el judge (Bloque 2)
- ❌ Scenarios versionados con git history (Bloque 2)
- ❌ Replay de conversaciones reales como scenarios (Bloque 2)
- ❌ Métricas agregadas históricas (Bloque 2)
- ❌ CI integration en cada PR (Bloque 1)
- ❌ Mock de helpdesks (el grafo no envía al helpdesk; el caller post-grafo se omite en simulation runner)
- ❌ Pruebas de skills no-Shopify (no hay otras providers commerce)
- ❌ Job queue (Celery/RQ) — `asyncio.gather` con semáforo basta hasta 10-20 tenants

---

## 16. Orden de implementación

```
1.  SQL migration                                → aplicar en staging
2.  db/models.py + db/queries.py                 → tipos y queries
3.  simulator/mocks.py + MockShopifyAdapter      → testeable aislado
4.  simulator/assertions.py                      → testeable, sin LLM
5.  Cambios en producción:
    - agents/state.py (2 campos)
    - skills/base.py (1 campo)
    - 11 skills shopify (1 línea c/u)
    - execute_skill node (bloque)
    - respond/escalate/finalize_trace: sin cambios
6.  simulator/user_simulator.py                  → testeable con mocks de Anthropic
7.  simulator/cost_guard.py                      → cost caps + rate limits
8.  simulator/runner.py                          → integración con grafo + semáforo
9.  simulator/judge.py + prompts.py
10. simulator/scenarios/ + seed script
11. routers/simulations.py                       → REST API con gates
12. Tests E2E: CE-01 y RE-01 pasan
13. UI super_admin (apps/web)                    → último
```

**Checkpoint mínimo** antes de seguir: CE-01 y RE-01 pasan con judge ≥ 7 corriendo desde script CLI.

---

## 17. Cambios en producción — diff total

**Estado real tras implementación (2026-05-25):**

| Archivo | Cambio | Estado |
|---|---|---|
| `agents/state.py` | + `simulation_mode`, `simulation_fixtures` | ✅ hecho |
| `agents/nodes/execute_skill.py` | `build_skill_context` inyecta `MockShopifyAdapter` si `simulation_mode` | ✅ hecho |
| `skills/base.py` | + `commerce_mock: Any` en SkillContext | ✅ hecho |
| `skills/shopify/*.py` (×11) | `adapter = ctx.commerce_mock or ShopifyAdapter()` | ✅ hecho |
| `db/queries.py` | queries nuevas + filtro `is_simulation = FALSE` en list/stale/nudge + `is_simulation` en create_conversation | ✅ hecho |
| `db/models.py` | + `is_simulation` en Conversation; UserProfile, SimulationScenario, SimulationRun | ✅ hecho |
| `agents/nodes/respond.py` | NINGUNO — el nodo no hace I/O externo | ✅ no se toca |
| `agents/nodes/escalate.py` | NINGUNO — idem | ✅ no se toca |
| `agents/nodes/finalize_trace.py` | NINGUNO — observabilidad la cierra el caller | ✅ no se toca |

**Total real**: 11 skills × 1 línea + execute_skill (1 bloque) + 2 campos de state + 1 campo de SkillContext. Menos invasivo que lo estimado: respond/escalate/finalize_trace quedan intactos.

**Validación**: migration aplicada contra Postgres local (3 tablas, 10 índices, 3 RLS, 3 triggers, smoke insert OK); 914 tests existentes pasan (cero regresiones); 16 tests nuevos para mocks + assertions pasan; ruff limpio.
