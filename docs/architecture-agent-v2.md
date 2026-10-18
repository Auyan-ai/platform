# Arquitectura del Agente — v2

> **Estado 2026-07-17:** el diseño v2 está **implementado y verificado en vivo** (dogfood Marea:
> L1, L3 con approval, resolución autónoma, Chatwoot/Gorgias E2E). Este doc es el **mapa
> conceptual**: qué piezas existen, por qué, y las decisiones que las gobiernan. **En el detalle
> manda el código + tests** — cada sección apunta a los archivos reales. El estado operativo vive
> en [`progress.md`](progress.md). La versión original de este doc (con todo el código inline de
> diseño, 2026-05) está en el historial de git de este archivo.

---

## 1. Resumen ejecutivo

Cuatro cambios estructurales sobre el agente v1 (que solo sabía responder/escalar con RAG):

1. **Skills framework** — cada acción es una clase tipada (I/O Pydantic), registrada, versionada
   y audit-logged. Tiers L1 (lectura) / L2 (escritura reversible) / L3 (destructiva).
   → `apps/api/skills/` (base, registry, shopify/ con 11 skills).
2. **AOPs (Agent Operating Procedures)** — el comportamiento vive en procedimientos YAML+Markdown
   editables en runtime desde el dashboard, versionados append-only, con workspaces
   staging/production. → `apps/api/aops/` (compiler, cache, canonical).
3. **Supervisor pattern** — un segundo modelo evalúa el reasoning antes de ejecutar escrituras.
   → `apps/api/agents/nodes/supervise.py`.
4. **Slow agent** — job batch LLM-as-judge que analiza conversaciones y propone diffs al AOP para
   aprobación humana. → `apps/api/slow_agent/`.

Transversal desde el día 1: idempotency, audit log, feature flags por tenant, workspaces.

## 2. Inspiración de la industria

| Concepto | Origen | Aplicación en Auyan |
|---|---|---|
| `SKILL.md` YAML frontmatter | Sierra Agent SDK | Schema de AOPs: frontmatter + cuerpo natural |
| Tools scopeadas por playbook | Sierra | `allowed_skills` por AOP → solo esas tools van al LLM |
| Deterministic guardrails | Sierra | Guardrails del AOP que el supervisor verifica explícitamente |
| Lenguaje natural editable runtime | Decagon AOPs | Body markdown editable sin redeploy |
| Versionado append-only | Decagon | `aop_versions` inmutable |
| Workspaces prod/staging | Decagon | Por (tenant, slug); promote = operación explícita con eval gate |
| Constellation of models | Sierra | Principal + supervisor. **Sin el "90%×90%→99%" del marketing** (errores correlacionan); se mide `supervisor_override_rate` real |
| Tiered risk + activación progresiva | Decagon | L1 día 1, L2 opt-in, L3 tras estabilidad + approval humano |
| Slow agent / Duet | Decagon | Job LLM-as-judge → proposals con evidencia |

## 3. Grafo (LangGraph, 12 nodos + loops)

→ `apps/api/agents/graph.py`, `agents/nodes/`, `agents/state.py`.

```
load_tenant_context → load_conversation → resolve_identity → select_aop → retrieve_knowledge → reason
    reason ⇄ execute_skill        (loop ReAct, tope max_tool_iterations por AOP)
    reason → supervise → …        (solo tools L2/L3 o require_supervision)
    reason → respond | escalate | handle_error → finalize_trace
```

Decisiones vigentes del routing (evolucionadas post-diseño, con PR):

- **Identidad en código** ([ADR 0013](adr/0013-verificacion-identidad-por-niveles.md)):
  `resolve_identity` convierte la evidencia del remitente (`messages.metadata.identity_evidence`,
  la escribe el intake según el origen) en grants con claims hasheados. `reason` solo ve las
  skills encendidas en `tenant_tool_permissions` que esa identidad permite, y el gate de
  `execute_skill` comprueba el pedido concreto de cualquier skill con `identity_scope`.
- **Sin checkpointer**: el state se arma desde cero por mensaje. La continuidad de intent viene de
  `intent_classifier_runs` (el clasificador ve el AOP previo) + **histéresis determinista**
  (continuidad / salir-de-default fácil / pivote requiere `intent_switch_threshold=0.70` /
  anti-flapping) — fix #5, [#167](https://github.com/Auyan-ai/platform/pull/167).
- **Supervisor selectivo**: no supervisa cortesía sin tools ([#191](https://github.com/Auyan-ai/platform/pull/191))
  ni lecturas L1 intermedias ([#229](https://github.com/Auyan-ai/platform/pull/229)); con tool
  pendiente el criterio es el tier L2/L3. Re-supervisa tras retry ([#218](https://github.com/Auyan-ai/platform/pull/218)).
- **Señales residuales anuladas**: cada retorno de `reason` anula la rama contraria (una tool
  rechazada no puede quedar viva en `pending_tool_call`) — [#214](https://github.com/Auyan-ai/platform/pull/214).
- **Router por complejidad**: Haiku en turnos sin skills posibles (AOP `smalltalk`), Sonnet en el
  resto — [#220](https://github.com/Auyan-ai/platform/pull/220)/[#221](https://github.com/Auyan-ai/platform/pull/221).
- **Prompt caching**: system+tools con `cache_control`; bloque estable (AOP) separado del volátil
  (fecha/facts/RAG); el feedback del supervisor va en bloque dinámico para no romper el prefijo —
  [#211](https://github.com/Auyan-ai/platform/pull/211)/[#228](https://github.com/Auyan-ai/platform/pull/228).
- **Resolución autónoma**: `respond` marca `resolved` vía señal `awaiting_customer_reply`, cierra
  el ticket externo, reabre si el cliente vuelve — [#196](https://github.com/Auyan-ai/platform/pull/196).
  Esto alimenta `resolution_events` (billing).
- **handle_error también escala al helpdesk** (reusa la escalación abierta) — [#215](https://github.com/Auyan-ai/platform/pull/215).
- **Ningún fallo cierra el turno sin escalar** (#362): los nodos del turno viven en la tabla
  `TURN_NODES` de `graph.py`; `build_graph` envuelve cada uno con `guarded` y desvía su salida a
  `handle_error` si hay `error`. Si el grafo entero lanza (límite de recursión, `handle_error` sin
  DB), `AgentService` escala con el mismo `handle_error` y, si tampoco puede, re-lanza para que el
  worker reintente o el webhook de chat dé 500. `tests/test_graph_failures.py` fuerza la excepción
  en cada nodo de la tabla y falla si aparece un nodo nuevo sin escenario.
- **Modelos por rol y traducción por modelo** (#344, #345): `ModelRegistry` (`core/config.py`)
  fija un modelo por rol y, con `THINKING_BY_ROLE` / `EFFORT_BY_ROLE`, su thinking y esfuerzo.
  `integrations/model_capabilities.py` dice qué acepta cada ID. Los nodos piden una decisión con
  una tool (`call_claude_for_decision`) o un texto (`call_claude_text`) y esa pieza arma la
  petición: tool forzada en Haiku 4.5, Sonnet 4.6 y Opus 4.7; `auto` + `strict` + instrucción,
  thinking adaptive y esfuerzo explícito en los 5.5. Sin decisión (refusal, sin tool tras un
  reintento, max_tokens) hay un `NoDecision` explícito: `reason` escala por `handle_error`,
  `select_aop` cae a `default` y el supervisor rechaza como structural.
  `tests/test_model_requests.py` fija la petición HTTP de cada nodo por modelo.

## 4. Skills framework

→ `apps/api/skills/base.py` (clase `Skill`: slug `vendor.action`, tier, schemas Pydantic,
`to_anthropic_tool()`), `skills/registry.py` (registry por decorator), `skills/shopify/`.

| Tier | Naturaleza | Activación | Threshold | Supervisor | Extra |
|---|---|---|---|---|---|
| L1 | Read-only | Día 1 | 0.70 | No | Trace LangSmith |
| L2 | Write bajo riesgo | Opt-in `tenant_tool_permissions` | 0.85 | Sonnet | Idempotency + audit |
| L3 | Write destructivo/financiero | Opt-in tras estabilidad | 0.95 | Sonnet (Opus solo crítico) | **Approval humano por defecto** |

**Piso L3 (s71, [#231](https://github.com/Auyan-ai/platform/pull/231)):** una L3 exige approval
humano salvo opt-out RECONOCIDO (`l3_autonomy_acknowledged_at/_by`; NULL = fail-safe). El endpoint
rechaza 422 si se desactiva el approval sin `acknowledge_l3_autonomy=true`.
→ `execute_skill._l3_requires_human_approval`, `routers/tool_permissions.py`.

**Flujo de approval L3** (verificado E2E s62): gate → `pending_approval` + mensaje cálido al
cliente (redactado con Haiku) → aprobación en dashboard (ambos roles, cada uno el suyo) →
ejecución real → confirmación natural → audit. Anti-duplicado determinista comparando la acción
con `order_id` resuelto ([#188](https://github.com/Auyan-ai/platform/pull/188)/[#218](https://github.com/Auyan-ai/platform/pull/218)).

## 5. AOPs

→ `apps/api/aops/compiler.py` (compilación), `aops/canonical.py` (**los 9 AOPs por defecto**:
8 e-commerce ES + `smalltalk`; copy-on-create al provisionar), tablas `aops` + `aop_versions`
(append-only), `routers/aops.py`.

**Anatomía**: frontmatter YAML (`slug`, `triggers`, `allowed_skills`, `required_data`,
`guardrails`, `max_tool_iterations`, `confidence_threshold`, `require_supervision`,
`escalation_triggers`, `steps[]` opcional) + body markdown ("cómo te comportas").

**Compilación a system prompt por bloques**: A identidad del tenant (el **tono NO va en el AOP** —
vive en `tenant_config.agent_voice`) · B procedimiento · C guardrails · D datos requeridos ·
E chunks KB (si hay) · F reglas globales (anti-invención incondicional, concisión 1-3 frases,
texto plano para chat, escalation triggers). Las tools que llegan al API call son SOLO las
`allowed_skills` del AOP filtradas por `tenant_tool_permissions`.

**Workspaces**: production (default del grafo) / staging. Promote staging→production es explícito
y pasa por el **eval gate** (pass_rate ≥ 80%; sin fixtures = no promote). Cache TTL 60s con
invalidación por Postgres LISTEN/NOTIFY.

**Secuenciación anti-retry** ([#233](https://github.com/Auyan-ai/platform/pull/233)): los AOPs
que afirman datos verificables (plazos, políticas) ordenan "el dato va primero, la afirmación
después" — mata el ciclo reject+retry del supervisor.

## 6. Selector de intent (`select_aop`)

→ `apps/api/agents/nodes/select_aop.py`, tabla `intent_classifier_runs`.

- Haiku con la tool `select_aop` (forzada donde el modelo lo acepta); devuelve **top-2
  candidatos + confidence + ambiguity_detected**. Sin decisión del LLM → AOP `default`.
- **Continuity-aware** (fix #5): ve el AOP previo de la conversación y aplica histéresis (ver §3).
- Degradación resiliente: output inválido del clasificador → AOP `default`, nunca tumba el turno
  ([#216](https://github.com/Auyan-ai/platform/pull/216)).
- AOP `default` obligatorio por tenant (en canónicos trae 4 skills L1 de consulta).
- **LLM, no embeddings**: la clasificación depende del contexto conversacional. Embedding router
  como pre-filtro queda en backlog.

Métricas (desde `intent_classifier_runs`): confidence por AOP, misclassification (corrección
humana), ambiguity rate, fallback rate a `default`, reclassification rate.

## 7. Supervisor

→ `apps/api/agents/nodes/supervise.py`.

- Se activa con tools L2/L3 pendientes o `require_supervision` del AOP (ver excepciones en §3).
- Ve **la misma evidencia que `reason`**: su system prompt (datos de la tienda, playbook,
  AOP y reglas) en el prefijo cacheado, y el bloque volátil del turno, el historial completo y
  la salida completa de las herramientas en el mensaje
  ([#261](https://github.com/Auyan-ai/platform/pull/261), #327). Ambos salen de
  `agent_system_blocks` en `reason.py`.
- **Contactos en código** (#327): un email o teléfono de la respuesta que no aparece en esa
  evidencia (sin contar lo que dijo antes la propia IA ni el feedback del supervisor) se
  rechaza como tactical sin llamar al LLM (`services/contact_grounding.py`).
- Verdict `approve|reject` + `reject_kind`: **tactical** (reintentable, 1 retry con feedback en
  bloque no-cacheado) vs **structural** (escala directo, sin retry).
- **Calibración vigente** ([#228](https://github.com/Auyan-ai/platform/pull/228)): sesgo por
  defecto a APROBAR — "red de seguridad, no editor de estilo"; un reject tactical debe nombrar la
  corrección concreta o aprueba.
- **Modelos**: Sonnet por defecto también para L3 (decisión de costo s63); Opus solo en casos
  críticos/calibración explícita.
- **Sin veredicto** (refusal o sin tool): reject structural con la razón (`llm_refusal: …`).
- **Un rechazo que escala** (structural, sin veredicto o segundo tactical) mueve el borrador de
  `agent_response` a `rejected_draft` en `supervise` (#380). El cliente recibe el acuse fijo de
  escalado; el borrador queda en `escalations.metadata.rejected_draft` y en la nota interna del
  helpdesk (`AgentOutcome.escalation_note`), marcado como rechazado. Si el supervisor lanza,
  `handle_error` escala y `AgentService` no entrega el borrador.
- Métricas: `supervisor_override_rate` (>20% = AOP flojo; por kind: structural alto = routing,
  tactical alto = AOP ambiguo), latencia, costo, y el delta honesto
  `write_error_rate` con/sin supervisor.
- Anti-patrón: **no supervisar al supervisor** (mejora offline con evals, no otra capa runtime).

## 8. Eval harness + simulator

→ `apps/api/evals/` (harness, mocks, fixtures YAML por AOP, assertions),
`apps/api/simulator/` (user_simulator Haiku, runner multi-turno, judge 4 dimensiones),
`routers/simulations.py`, UI super_admin.

- **Tres tipos de test**: unit / integration / simulation (multi-turno).
- **Judge 4 dimensiones** (alineado Sierra): Reasoning / Knowledge / Tools / Brand voice.
  Sonnet judge por defecto; Opus opcional. Cap de costo por corrida.
- **Gate**: PR a develop = suite completa bloqueante; promote de AOP = fixtures del AOP ≥80%;
  propuesta del slow agent = `requires_eval_pass`.
- **Inventario mínimo por AOP**: 13 fixtures (5 happy, 3 edge, 3 escalación, 2 adversarial).
- 🔴 **Deuda viva**: fixtures huérfanas con slugs legacy ≠ canónicos → el gate de promote está
  de facto apagado para los AOPs reales (ver `progress.md`).

## 9. Audit, PII, idempotency

→ `skill_audit_log` (todas las tiers, con `inputs_redacted` + `inputs_hash`),
`services/pii.py`, `skill_idempotency`.

- **PII**: pseudonimización SHA-256 + salt por tenant (rotable = olvido GDPR); redacción de
  dirección/CP en copia forense con `inputs_raw` para el operador ([#198](https://github.com/Auyan-ai/platform/pull/198)).
  Hashing en app, no en DB. Acceso cross-tenant solo super_admin, registrado.
- **Idempotency**: key UUIDv7 generado por el grafo (NUNCA por el LLM) antes de ejecutar L2/L3;
  mismatch de `inputs_hash` = error explícito. El dedup del gate L3 incluye el `order_id`
  resuelto ([#218](https://github.com/Auyan-ai/platform/pull/218)).
- **Preparación en código**: `Skill.prepare` corre antes de decidir si hace falta aprobación,
  con y sin ella, y lo que devuelve sustituye a los inputs del LLM. `refund_partial` fija ahí
  la moneda del pedido y rechaza importes por encima de lo reembolsable (#265);
  `start_return` y `start_exchange` dejan el plan de la política con su liquidación (ADR 0014).
  Un `SkillRefusal` escala con texto fijo; un `SkillRejection` vuelve al LLM como error tipado
  (`skill_rejected: <code>: <detalle>`) para que pida lo que falta. La aprobación es
  obligatoria si la exige el piso L3 o `Skill.requires_approval(prepared)`.
- **Devoluciones y cambios** (ADR 0014): `services/returns.evaluate_return` aplica la política
  del tenant (`tenant_returns_policies`, cargada en `load_tenant_context`) al pedido releído
  de Shopify; sin política, rechazo y escalado. El resumen de la política entra en el bloque
  volátil del turno. Tras ejecutar sin aprobación, las skills con `reply_from_outcome` cierran
  el turno con el texto fijo de su resultado.
- **Memoria de hechos del turno**: datos ya leídos se inyectan a reason+supervisor desde
  `skill_audit_log`, invalidando tras mutación ([#189](https://github.com/Auyan-ai/platform/pull/189));
  las acciones L3 completadas también van al contexto ([#192](https://github.com/Auyan-ai/platform/pull/192)).

## 10. Lifecycle de conversación

→ `services/cleanup.py`, estados en `db/models.py`.

Estados: `open / pending / escalated / resolved / closed / closed_abandoned`.
Timeouts y nudge por canal en `tenant_config.conversation_lifecycle`. La **resolución autónoma**
([#196](https://github.com/Auyan-ai/platform/pull/196)) cierra/reabre también el ticket del
helpdesk externo. Reapertura con `previous_conversation_id` = backlog Bloque 4.
Métricas: abandonment_rate, nudge_recovery_rate, reopen_rate.

## 11. Slow agent

→ `apps/api/slow_agent/` (transcript, judge, runner, sampling), tabla `improvement_proposals`,
`routers/proposals.py`, UI cola de propuestas.

- **Sampling** (no todo desde el día 1): siempre escaladas + L2/L3; ~10% del resto.
- **Two-step judge**: Sonnet → Opus solo si confidence <0.7.
- Propuestas tipadas (`aop_edit | new_aop | skill_request | guardrail_addition`) con
  `diff_markdown`, `rationale`, `evidence_conversations` y `requires_eval_pass`.
- Métricas de salud: `proposal_acceptance_rate` (<20% = basura, >60% = encontró la voz),
  `cost_per_useful_proposal` (<$50), `time_to_first_proposal_per_tenant`.

## 12. Escalación y adapters (post-pivot)

→ `apps/api/integrations/` (protocolos `MessageProvider`/`HelpdeskProvider` + registry),
`services/helpdesk_escalation.py`, `services/helpdesk_delivery.py`, tabla `tenant_integrations`
(credentials cifradas app-level con la key del entorno).

- Adapters vigentes: **Chatwoot** (API key, E2E ✅), **Gorgias** (dual-auth Bearer|Basic, E2E ✅,
  outbound espeja el último mensaje entrante + `body_html`), **Zendesk** (dual-auth, código ✅,
  E2E pendiente), **Postmark** (outbound Auyan→cliente). Shopify = `CommerceProvider` aparte.
- Escalación = push al helpdesk del cliente (nota interna en lenguaje natural con el motivo;
  asignación a equipo solo si el tenant tiene Teams; email fallback sin helpdesk).
  `escalations` guarda `external_provider` + `external_ticket_ref`.
- **Shadow mode** = drafts como internal notes; activación gradual **por categoría** con
  aprobación explícita del cliente. Bloque 3 lo evoluciona a canary (5%→100%) con
  `agent_traffic_splits` y rollback por threshold.

## 13. KB de tres niveles + playbook

🔴 Solo Auyan: prompts, AOPs, RAG. 🟡 Cliente aporta → Auyan cura: `tenant_knowledge_submissions`
(drop-zone, cola pending review). 🟢 Cliente edita: `tenant_facts` (contexto estructurado directo
al agente, NO entra al RAG; schema editable por vertical). `tenant_playbook` = la "Biblia" del
cliente en DB, versionada, solo dashboard interno.

**RAG degrada elegante**: si embeddings caen → `chunks=[]` y el agente sigue (la búsqueda en
Postgres sí es fail-fast) — [#219](https://github.com/Auyan-ai/platform/pull/219).

## 14. Anti-patrones (vigentes, no negociables)

- ❌ Skills fuera del scope del AOP (cancel_order no va en consulta_envio).
- ❌ El LLM nunca genera idempotency keys ni rellena país/datos deterministas
  ([#194](https://github.com/Auyan-ai/platform/pull/194)).
- ❌ `aop_versions` jamás se edita — append-only.
- ❌ AOPs no se commitean al repo (viven en DB; `aops/canonical.py` es el seed).
- ❌ L3 nunca se salta supervisor + approval "porque la confidence es alta".
- ❌ No supervisar al supervisor.
- ❌ No correr el slow agent sobre todo desde el día 1 (sampling primero).
- ❌ No vender el "90%×90%→99%" ni internamente.
- ❌ Tono de tenant dentro de un AOP (va en `agent_voice`).
- ❌ No promover AOP a production sin pasar evals.
- ❌ No enmascarar fallos de skills con mensajes tranquilizadores — fallo honesto
  ([#180](https://github.com/Auyan-ai/platform/pull/180)); tool vacío/error = dato no disponible,
  nunca inventar plazos/tracking/políticas.

## 15. Backlog técnico priorizado (context engineering)

Gaps aún abiertos del análisis Sierra (sesión 19), en orden:

1. **Memory cross-conversación** (alta) — resumen de conversaciones previas del mismo
   `end_customer_id`. Sierra/Decagon ya lo shippearon en 2026.
2. **Glossary block** (alta) — terminología de marca como bloque propio del compiler.
3. Condiciones por observación mid-turno (media).
4. Brand voice override por AOP (media).
5. KB re-retrieval mid-ReAct (baja) · selección condicional de tools (baja) ·
   `ContextBlock` first-class (baja).

Backlog Bloque 4: reapertura con `previous_conversation_id`, detección automática de
alucinaciones, voz, Intercom adapter, WhatsApp directo, modo proactivo, embedding router,
MCP server.
