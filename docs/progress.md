# Auyan — Estado actual

_Última actualización: 2026-06-27 (sesión 73 — **LangSmith node-level tracing + fix crítico de seguridad.** Antes los traces de LangSmith solo mostraban `agent_conversation` → `agent_model_call` (tokens/costo agregados); el detalle nodo-por-nodo del grafo (select_aop, reason, execute_skill, supervise…) solo vivía en el dashboard de "Agent reasoning" (Supabase `reasoning_events`). [#237](https://github.com/Auyan-ai/platform/pull/237) MERGEADO: wrapper genérico `_traced` en `build_graph` emite un child run (`run_type=chain`) por cada nodo del grafo con nombre, duración y outputs allowlisteados — cero cambios en los nodos; `record_node_run` en `LangSmithClient`+`ObservabilityClient`; trace propagado vía `AgentState._trace_run_id/_trace_dotted_order` y `observability` en `AgentDependencies`. **🔴 Fix de seguridad [#238](https://github.com/Auyan-ai/platform/pull/238) MERGEADO (Kenny lo cazó en review):** el wrapper original mandaba el dict de output COMPLETO de los nodos sin allowlist a LangSmith (SaaS de terceros) → filtraba el **access token de Shopify descifrado** (`load_tenant_context.commerce_integration_ctx.credentials.token`) y **PII** (`load_conversation.conversation_history`/`end_customer`). El #237 alcanzó a mergearse y deployar con el leak antes del fix → el token estuvo en traces de los webhooks de prueba de hoy. Fix: **allowlist estricta** (`_NODE_OUTPUT_KEYS.get(name, [])` → nodo sin entrada emite `{}`, solo timing del span) + **redacción recursiva defensiva** (`_redact_dict` tacha token/credentials/secret/api_key/password/authorization) + 6 tests de regresión en `test_graph_tracing.py` (uno prueba que el token jamás aparece en el payload). 1323 verde, ruff/mypy limpios. **Verificado EN VIVO sobre Marea** (trace `f21ab9a7…`): child runs presentes, `execute_skill` muestra el tool call de Shopify, `load_tenant_context`/`load_conversation` sin credenciales ni PII. **🔴 PENDIENTE: rotar el access token de Shopify de Marea** (estuvo expuesto en LangSmith entre #237 y #238) → regenerar en Shopify + re-registrar con `railway run … configure_staging_integrations`. Aprendizaje guardado en memoria [[feedback_observability_no_secrets]]: observabilidad nunca exfiltra secrets/PII — allowlist, no denylist.)_
> _Sesión 72 (2026-06-21) — **Sesión autónoma: 3 PRs MERGEADOS (Zendesk managed-auth, latencia del AOP returns, motor de Billing Bloque 2), suite 1306 verde.** Kenny pidió cerrar los 3 pendientes técnicos dejándole solo Customer Discovery; lo manual quedó en "Arranque sesión 73". [#232](https://github.com/Auyan-ai/platform/pull/232) **Zendesk dual-auth** (API token/Basic, espejo de la s69 de Gorgias) + provider `zendesk` en `configure_staging_integrations`: el enum `channel_type` ya tenía `zendesk` → **sin migración**; el outbound usa el shape estándar (`add_comment` público), **sin** la rareza `source.type`/`body_html` de Gorgias. [#233](https://github.com/Auyan-ai/platform/pull/233) **latencia HOPS por prompt**: el AOP `returns` ahora secuencia "el dato va primero, la afirmación después" (verificar la política en KB/`tenant_facts`/`get_shop_policies` ANTES de afirmar un plazo) → mata de raíz el reject+retry del supervisor; test de invariante en `test_canonical_aops`. [#234](https://github.com/Auyan-ai/platform/pull/234) **motor de Billing Bloque 2** (PRD §7 puntos 1+3): migración `resolution_events` (append-only) + `billing_subscriptions` (snapshot de floor/included/overage, RLS solo-lectura, campos `stripe_*` nullable), conteo por periodo mensual anclado con **ventana de reapertura** (§2.3), catálogo de tiers (números **PROVISIONALES**), `compute_period_usage`, hooks en `respond`/`reopen`, y `GET /billing/usage` + `PUT /billing/subscription`. **Stripe NO entró** (necesita key + dashboard → siguiente trozo aditivo). Suite **1306 verde**, ruff/mypy limpios. **#232/#233/#234 MERGEADOS.** **🔴 Pendiente: aplicar a mano las migraciones de billing (#234) + la del piso L3 (#231) + `add_gorgias_channel` en prod** (Railway no corre SQL). Ver "🚀 Arranque sesión 73" abajo.)_
> _Sesión 71 — **Auditoría de robustez del grafo + cierre del hallazgo 🔴 L3-sin-approval (Opción B, 2 PRs TDD).** Re-auditoría 12-capas: núcleo sólido (`tool_choice` code-gated, `@guarded`, degradación elegante, prompt caching, anti-inyección RAG); el riesgo vive en los bordes. **🔴 Hallazgo:** una L3 destructiva con `is_enabled=True`+`human_approval_required=False` se ejecutaba SIN aprobación humana, confiando solo en el supervisor (sesgado a APROBAR) — el seed de Marea tenía `start_return`/`update_shipping_address` así. **Raíz:** `human_approval_required=False` era ambiguo (opt-out consciente vs default de fábrica), fail-open en schema/función/runtime. **PR1 (piso):** `_l3_requires_human_approval` en `execute_skill` (L3 exige approval salvo opt-out RECONOCIDO) + migración `l3_autonomy_acknowledged_at/_by` (NULL=fail-safe, sin backfill → Marea cae del lado seguro sola) + señal propagada modelo→query→`load_tenant_context`. **PR2 (flexibilidad B):** endpoint rechaza 422 si se desactiva el approval de una L3 sin `acknowledge_l3_autonomy=true`; `upsert` sella/limpia el acknowledgment. **1297 tests verde, ruff limpio.** **PENDIENTE BLOQUEANTE: aplicar la migración a staging a mano ANTES del deploy** (Railway no corre SQL → si no, `load_tenant_context` hace SELECT de columnas inexistentes y escala todos los turnos). **Backlog de la auditoría:** #2 race de concurrencia (sin lock por conversación; la idempotencia es por `message_id`, no serializa 2 mensajes distintos), #3 entrega outbound best-effort tras marcar resuelto/cerrar ticket. Ver "🚀 Arranque sesión 73" abajo.)_
> _Sesión 70 — **Latencia de HOPS — 3 palancas, 2 PRs, validadas EN VIVO con traces (medir > adivinar).** Atacada la palanca de HOPS (turnos con supervisor encadenan llamadas LLM secuenciales; el peor caso s68 fue 3 reason + 2 supervise ≈ 20s). [#228](https://github.com/Auyan-ai/platform/pull/228): **P1 — el retry del supervisor ya no rompe el caché** (el feedback del reject se concatenaba al `system_prompt`, que vive en el bloque `cache_control` de #211 → el `reason#3` del retry hacía cache-miss total; ahora va en `state.supervisor_feedback` → `reason` lo inyecta como bloque dinámico NO cacheado; el prefijo queda bit-idéntico y el retry recupera el cache hit) + **P2 — calibración del supervisor** (sesgo por defecto a APROBAR, "red de seguridad no editor de estilo"; materialidad: un reject tactical debe nombrar la corrección concreta o aprueba). [#229](https://github.com/Auyan-ai/platform/pull/229): **P3 — no supervisar lecturas L1 intermedias** (en AOPs con `require_supervision`, `needs_supervision` mandaba a supervise la INTENCIÓN de leer una tool L1 como `get_shop_policies`; ahora con tool pendiente el único criterio es el tier L2/L3 — las mutaciones y el respond final se siguen supervisando). **VALIDADO EN VIVO (Marea staging, traces en `agent_reasoning_events`):** P1 confirmado — el `reason#3` del retry leyó `cache_r=2986` (antes 0). P3 confirmado comparando el MISMO turno de devoluciones antes vs después: `get_shop_policies` pasó de `tool_call → supervise → approve → result` (7 hops, 3 supervise) a `tool_call → result` directo (**6 hops, 2 supervise**). **Hallazgo de método:** P3 se descubrió mirando el trace, NO P2 — el reject del supervisor era LEGÍTIMO (afirmaba plazo de 30 días sin verificar con `get_shop_policies`); la palanca real era estructural. #228 y #229 MERGEADOS. **Ver "🚀 Arranque sesión 71" abajo.**)_
> _Sesión 69 — **Gorgias verificado E2E sobre Marea — Basic auth + 3 bugs del dogfood.** Habilitado Gorgias como canal real en staging (Marea) con **API Key / Basic auth** (no el OAuth2 Bearer existente, que caduca sin refresh): [#223](https://github.com/Auyan-ai/platform/pull/223) **adapter dual-auth** (Bearer|Basic) + `_is_from_agent` robusto (bool|string) en el webhook + script `configure_staging_integrations --only gorgias` (valida creds contra la API, cifra, registrado **no-primary**). **Migración faltante en staging aplicada a mano:** `add_gorgias_channel` (el enum `channel_type` no tenía `gorgias` → 500). **Dogfood E2E real (email→ticket) cazó 3 bugs, todos con PR+tests:** (1) el enum de arriba; (2) [#224](https://github.com/Auyan-ai/platform/pull/224) **outbound roto** (`source.type:"agent"` → 400 "Not a valid choice"; ahora `send_message` hace GET del ticket y **espeja el último mensaje entrante** — source from↔to, sender↔receiver — patrón que Gorgias exige); (3) [#226](https://github.com/Auyan-ai/platform/pull/226) **email vacío** (Gorgias arma el correo desde `body_html`; mandábamos solo `body_text` → autogeneraba un html solo-cita → correo en blanco; ahora derivamos `body_html` del texto). **Verificado EN VIVO punta a punta:** inbound→agente→outbound→**email con texto**→resolución (cierra el ticket)→reapertura→`order_status` fuera de plazo (#1181, 30-may, ~13 días unfulfilled > plazo de Marea, comparación días-vs-plazo en el AOP order_status)→**escalado** (nota interna con motivo+contexto; SIN asignar porque Marea no tiene `escalation_team_id` — la asignación es config per-cliente). Config en Gorgias = **HTTP Integration** (trigger *ticket-message-created*, body templado con `meta.domain={{ticket.account.domain}}`). **CLAUDE.md:** selección de modelo Fable/Opus/Sonnet con uso+costo (Fable = tier SOBRE Opus, ~2×, NO "Opus rápido"). [#225](https://github.com/Auyan-ai/platform/pull/225) chore: borrado `bloque-0-plan.md` + ref huérfana. **Chip vivo:** persistir `refresh_token` en el OAuth de Gorgias (`oauth_gorgias.py` lo descarta hoy). **Ver "🚀 Arranque sesión 70" abajo.**)_
> _Sesión 68 — **Auditoría 🟠 cerrada + latencia (palancas 2/3) medida en vivo**. Cerrados los 4 hallazgos 🟠 de la auditoría del grafo: [#218](https://github.com/Auyan-ai/platform/pull/218) **re-supervisar tras retry** (`supervisor_retried` dejaba de apagar la supervisión del turno; el anti-loop vive en el nodo supervise) + **`order_id` en el dedup del gate L3** (resuelve visible↔interno vía adapter; ya no se traga una acción L3 sobre OTRO pedido con inputs iguales; fail-safe = acción distinta); [#219](https://github.com/Auyan-ai/platform/pull/219) **guardrails estructurados al supervisor** (`CompiledAOP.guardrails` → state `aop_guardrails`, en vez de parsear el system_prompt con `split("Reglas NO negociables")`) + **RAG degrada a `chunks=[]`** si OpenAI embeddings cae (antes escalaba TODO; la búsqueda en Postgres sí sigue fail-fast). **Latencia palancas 2/3:** [#220](https://github.com/Auyan-ai/platform/pull/220) **router por complejidad** (`_select_reason_model`: Haiku en turnos sin skills/tool_results/pending — solo respond/escalate posible) + **concisión imperativa** (regla global: 1-3 frases por defecto, sin preámbulos de relleno); [#221](https://github.com/Auyan-ai/platform/pull/221) **9º AOP `smalltalk` sin skills** que ACTIVA el router. **MEDIDO EN VIVO (Marea staging):** el router #220 nunca se activaba porque TODOS los AOPs canónicos tienen skills (hasta `default`, 4 L1) → creado `smalltalk` (charla pura, `allowed_skills=[]`); el clasificador enruta "gracias" ahí → **Haiku 1,7s vs Sonnet 3,5s (~50% menos)**, sin supervisor. **Concisión confirmada:** respuesta de devoluciones 267-293 tok vs 476 baseline s67 (~40% menos output). **Hallazgo nuevo:** en turnos con tool+supervisor la latencia la dominan los HOPS secuenciales (devoluciones reales: 3 reason + 2 supervise ≈ 20s por un retry del supervisor), NO el output — palanca futura distinta. `smalltalk` **seedeado solo en Marea** (dogfood); rollout a los demás con `seed_canonical_aops --all` tras mergear #221. #218–#220 MERGEADOS; #221 abierto._
> _Sesión 67 — **Auditoría del grafo + 4 PRs de robustez + latencia medida**. A petición de Kenny, auditoría completa del grafo del agente (11 nodos + routing): 2 bugs 🔴, varios 🟠. Cerrados los 🔴 con TDD: [#213](https://github.com/Auyan-ai/platform/pull/213) **instrumentación latencia/cache** (`trace_label` en `call_claude_with_tools` loguea `dur_ms` + breakdown `in/cache_w/cache_r/out` por llamada — eran los 4 archivos sin commitear de sesión 66); [#214](https://github.com/Auyan-ai/platform/pull/214) **señales residuales en `reason`** (el merge por-key de LangGraph dejaba la tool RECHAZADA por el supervisor en `pending_tool_call` → `route_after_reason` la ejecutaba sin re-supervisión; espejo: un `agent_response` rechazado podía llegar al cliente vía escalate+max_iter — cada retorno de `reason` ahora anula la rama contraria); [#215](https://github.com/Auyan-ai/platform/pull/215) **handle_error → helpdesk** (las escalaciones por error de sistema NO empujaban nota al helpdesk del cliente: faltaba `escalation_created`; además insertaba escalación nueva por cada error → ahora reusa la abierta, patrón de `escalate`); [#216](https://github.com/Auyan-ai/platform/pull/216) **classifier resiliente** — destapado EN VIVO al medir: Haiku devolvió el tool output sin `ambiguity_detected` (required) → `ValidationError` tumbaba el turno entero por `agent_error`. Fix 2 capas: defaults en `_ClassifierOutput` + try/except → degradar a `default`. **Los 4 MERGEADOS, suite 1256 verde.** **Latencia MEDIDA en staging** (send_test_webhook + logs `llm_call`): el **caching pega y persiste entre turnos** (`cache_r=1982` se reusa en el turno siguiente, 46s después, dentro del TTL) — **#211 confirmado**. **Hallazgo clave: la latencia la domina el OUTPUT, no el input** (out=48→2,4s; out=476→7,7s; out=309→6,4s). El caching ya optimizó el input; las palancas reales son concisión, menos tool hops y modelo rápido en turnos simples. Latencia/turno: ~10s con tool (2 llamadas LLM), ~6,4s directo. Supervisor NO corrió (selectivo #191 OK). **Doc nuevo:** [`docs/market-analysis-2026-06.md`](market-analysis-2026-06.md) (rescatado de una rama huérfana `claude/market-analysis-*`): e-commerce vs otros verticales en ES, hallazgo Ley 10/2025 (energía), recomendación = bifurcar discovery en 2 cohortes, NO pivotar. **Ver "🚀 Arranque sesión 68" abajo.**)_
> _Sesión 66 — **Legibilidad del chat + prompt caching del agente**. 2 PRs MERGEADOS: [#210](https://github.com/Auyan-ai/platform/pull/210) **regla global de formato para chat** (texto plano, sin tablas/Markdown que el widget renderiza ilegibles; `aops/compiler.py::_render_global_rules`) verificado E2E; [#211](https://github.com/Auyan-ai/platform/pull/211) **prompt caching del system + tools** en `reason` y `supervise` (`cache_control` ephemeral; `build_system_blocks` separa AOP estable [cacheado] de volátil [fecha/known_facts/RAG]; la fecha ya NO va de preámbulo). Latencia palanca #1 (caching) hecha; medición confirmada en sesión 67._
> _Sesión 65 — **Cierre de deuda + enrutado del escalado al helpdesk**. 4 PRs: [#204](https://github.com/Auyan-ai/platform/pull/204) **retrofit DRY cripto** (load_tenant_context usa el helper `build_commerce_integration_ctx` — fuente única de la cripto de llaves, −199 líneas; cobertura de cripto movida a `tests/test_commerce_context.py`) MERGEADO; [#205](https://github.com/Auyan-ai/platform/pull/205) docs MERGEADO; [#206](https://github.com/Auyan-ai/platform/pull/206) **enrutado del escalado al helpdesk** (nuevo `services/helpdesk_escalation.py`: nota interna con el motivo + asignación al equipo CX; flag `escalation_created` empuja una sola vez, anti-duplicado; best-effort en los 4 webhooks) MERGEADO; [#207](https://github.com/Auyan-ai/platform/pull/207) **nota natural** (dogfood: la nota interna volcaba un JSON con confianza/trace/mensaje duplicado → ahora solo el motivo en lenguaje natural) ABIERTO. **Dogfood en vivo (Chatwoot):** un escalado real publicó la nota interna privada (candado 🔒, no la ve el cliente) con el contexto. **Hallazgo:** el Chatwoot de Marea/Purigu **no tiene Teams** habilitado → la auto-asignación queda diferida; por ahora solo la nota interna (NO setear `escalation_team_id`). **Siguiente:** Markdown en el widget. Ver "🚀 Arranque sesión 66" abajo.)_
> _Sesión 64 — **Chips post-dogfood + resolución autónoma + billing por resolución**. 8 PRs MERGEADOS a develop: [#194](https://github.com/Auyan-ai/platform/pull/194) **país determinista** en update_shipping_address (preserva el del pedido + fallback config, no lo inventa el LLM); [#195](https://github.com/Auyan-ai/platform/pull/195) **H4** plazo de devolución desde la recepción (get_order_status expone fulfilled_at/delivered_at; AOP returns mide desde entrega→envío→created_at); [#196](https://github.com/Auyan-ai/platform/pull/196) **resolución autónoma** (respond marca `resolved`+`resolved_at` vía señal `awaiting_customer_reply` del decide tool; cierra ticket externo tras entregar; reabre si el cliente vuelve; cleanup entrega nudge + cierra abandonadas — migración `resolved_at` **APLICADA en staging**); [#197](https://github.com/Auyan-ai/platform/pull/197) **observabilidad** L3 (approve loguea la ejecución real en `skill_audit_log`); [#198](https://github.com/Auyan-ai/platform/pull/198) **PII** (redacción de dirección/CP en copia forense; operador ve `inputs_raw`); [#199](https://github.com/Auyan-ai/platform/pull/199) **limpieza** (dead code middleware + `reply_model` setting); [#200](https://github.com/Auyan-ai/platform/pull/200) **PRD billing**; [#202](https://github.com/Auyan-ai/platform/pull/202) **order_status fuera de plazo** (no da falsa tranquilidad a un pedido vencido: compara días vs plazo de envío → reconoce el retraso y escala). **Marea re-seedeada** (AOPs canónicos v6 con país/H4/order_status). **Validado E2E en vivo** (widget Chatwoot real): resolución autónoma resolve→reopen→resolve (el ticket de Chatwoot se cierra/reabre solo), país determinista, y order_status escalando un pedido fuera de plazo. **COGS real medido** en una conversación completa: ~$0,077 ≈ **€0,071/resolución** (valida el PRD, incluso por debajo). **Decisión de negocio:** unidad de cobro = **resolución** (cierre sin escalar) con **suelo + overage** → PRD [`docs/billing-resolution-prd.md`](billing-resolution-prd.md) + issue [#201](https://github.com/Auyan-ai/platform/issues/201). **Ver "🚀 Arranque sesión 65" abajo para lo pendiente.**_
> _Sesión 63 — **Dogfood L3 endurecido — 13 PRs (#180–#192)**. Verificación E2E del flujo de cambio de dirección sobre Marea (widget Chatwoot real), analizando conversaciones + traces en Supabase. La primera tanda cerró los 6 hallazgos del análisis inicial: [#180](https://github.com/Auyan-ai/platform/pull/180) fallo L3 honesto (no enmascarar un 404 con "estamos revisando"; queda `pending` para reintento); [#181](https://github.com/Auyan-ai/platform/pull/181) resolver el **número de pedido visible → order_id interno** en las 6 skills de mutación (causa raíz del 404); [#182](https://github.com/Auyan-ai/platform/pull/182) mensaje del gate L3 cálido/contextual; [#183](https://github.com/Auyan-ai/platform/pull/183) no duplicar el gate (idempotencia sobre `pending`); [#184](https://github.com/Auyan-ai/platform/pull/184) **read-back** de la dirección antes de aprobar; [#185](https://github.com/Auyan-ai/platform/pull/185) inferir país (tienda) y provincia (CP), no pedirlos a ciegas. Re-probar destapó 7 más: [#186](https://github.com/Auyan-ai/platform/pull/186) no re-disparar la skill tras aprobar (prompt); [#187](https://github.com/Auyan-ai/platform/pull/187) concisión global (no repetir info ya dada); [#188](https://github.com/Auyan-ai/platform/pull/188) **red determinista** anti-duplicado (reusa approval pending/approved comparando la acción sin `order_id`); [#189](https://github.com/Auyan-ai/platform/pull/189) **memoria de hechos** (inyectar datos ya leídos en reason+supervisor desde `skill_audit_log`, invalidando tras mutación) — corta re-consultas; [#190](https://github.com/Auyan-ai/platform/pull/190) mensaje coherente al reescribir tras una acción ya aplicada (no "sigue en revisión"); [#191](https://github.com/Auyan-ai/platform/pull/191) **supervisor selectivo** (no supervisar respuestas de cortesía sin tools); [#192](https://github.com/Auyan-ai/platform/pull/192) inyectar **acciones L3 completadas** en el contexto para no re-disparar el gate ante un "gracias" — **ABIERTO**, #180–#191 MERGEADOS. **Latencia:** read-back de ~16s → **~5s**. **Decisión:** supervisor en **Sonnet** (Opus solo crítico) por costo. **Re-seeds aplicados a Marea** tras #184/#185/#186; welcome del widget Chatwoot desactivado (evita doble saludo). Pendiente: verificar #192 en vivo, y deuda de **fixtures de eval huérfanas** (slugs legacy ≠ canónicos). Ver "Dogfood E2E Marea" abajo._
> _Sesión 62 — **Dogfood L3 cerrado E2E + 6 fixes**. Cerrado el flujo L3 con approval de punta a punta vía **widget Chatwoot real** (`order_change` → `update_shipping_address` sobre #1181: gate → `pending_approval` → aprobación en dashboard → ejecución real en Shopify → confirmación al cliente → revert a la dirección original). El camino de aprobación estaba **roto de raíz**; el dogfood destapó 5 bugs + 1 de seguridad, todos con PR + tests: [#172](https://github.com/Auyan-ai/platform/pull/172) **H5** colisión `account_id` cross-tenant (índice único parcial + guard fail-closed); [#173](https://github.com/Auyan-ai/platform/pull/173) 500 al aprobar (SkillContext con kwargs obsoletos → helper `build_commerce_integration_ctx`); [#174](https://github.com/Auyan-ai/platform/pull/174) **B1** el dashboard interno no exigía `super_admin` (un `tenant_admin` podía entrar — no era fuga de datos, la API aísla, pero sí frontera de operador rota); [#175](https://github.com/Auyan-ai/platform/pull/175) 500 mensaje `agent_human` sin autor (constraint); [#176](https://github.com/Auyan-ai/platform/pull/176) 422 país en texto libre ("España") → `country_code` ISO; [#177](https://github.com/Auyan-ai/platform/pull/177) mensaje al cliente crudo → redactado con **Haiku** (fallback plantilla); [#178](https://github.com/Auyan-ai/platform/pull/178) **entrega al helpdesk** de los mensajes del flujo L3 (escalate + approve) — **ABIERTO**, resto MERGEADOS. `complaint` también verificado (empatía + escalar, sin L3). **Decisión de producto:** ambos roles aprueban L3, cada uno desde su dashboard (la API ya aísla por tenant). Pendiente: **país determinista** (hoy lo rellena el LLM), H4, H6. Ver "Dogfood E2E Marea" abajo._
> _Sesión 61 — **Fix de raíz Hallazgo 1 (provisioning)**: `provision_tenant` ahora crea `tenant_configurations` + prompt base `system` (helper idempotente `ensure_tenant_config_and_prompt` + script de backfill). [PR #171](https://github.com/Auyan-ai/platform/pull/171) MERGEADO._
> _Sesión 60 — **Fix #5 intent-switch continuity-aware** ([#167](https://github.com/Auyan-ai/platform/pull/167) MERGEADO, cierra 5/5 fixes de grafo) + **dogfood E2E sobre Marea** (Fix #5 multi-turno + order_status #1181 + returns/refunds + **Chatwoot real**) → destapó hallazgos #168 (política KB/facts) y #169 (token Shopify en claro), MERGEADOS._
> _Sesión 59 — **AOPs canónicos + fixes de grafo**. (1) Diseñados y verificados uno a uno los 8 AOPs por defecto de e-commerce ES en [`docs/aop-canonical-design.md`](aop-canonical-design.md). (2) **PR #1 [#163](https://github.com/Auyan-ai/platform/pull/163) MERGEADO**: provisioning copy-on-create — cada tenant nace con sus 8 AOPs + permisos (L1/L2 auto, L3 con approval) vía hook en `provision_tenant`; `aops/canonical.py` es la fuente de verdad + `scripts/seed_canonical_aops.py` para backfill. (3) Fixes de grafo (PR #2): [#164](https://github.com/Auyan-ai/platform/pull/164) (cablear `confidence_threshold` + `require_supervision` por-AOP, antes muertos; guard anti prompt-injection) y [#165](https://github.com/Auyan-ai/platform/pull/165) (fecha/hora TZ-aware del tenant + dep `tzdata`) — **AMBOS ABIERTOS, esperan review/merge**. (4) **Backfill aplicado en staging**: Marea Studio (8 nuevos) y Lunaria (6 nuevos + returns/default actualizados a canónico, `consulta_envio` viejo desactivado) — los 8 canónicos activos + 11 permisos en ambos. PENDIENTE: **Fix #5 intent-switch en sesión nueva** — ver sección abajo)._

> Historial completo en [`docs/progress-archive.md`](progress-archive.md). Contexto estratégico en [`docs/auyan-master-context.md`](auyan-master-context.md).

---

## 🚀 Arranque sesión 73 — pendientes priorizados

**Modelo:** Sonnet para fixes acotados e integraciones; Opus para latencia (diseño del grafo), billing y RLS. Fable solo si Opus se queda corto (~2× el costo).

**Rama:** `develop` (sesión 72 mergeó #232–#234; sesión 71 mergeó #231). **Migraciones a mano** (Railway no corre SQL; [[reference_supabase_migrations]]):
- ✅ **Staging al día — aplicadas y VERIFICADAS EN VIVO (s72):** `20260617000000_add_l3_autonomy_acknowledgement.sql` (#231) + `20260621000001_add_billing_resolution_events.sql` (#234). Verificación E2E sobre Marea (un turno de devoluciones vía `/webhooks/inbound`): `respond` **sin** `agent_error` (fix L3 OK, antes escalaba todos los turnos), respondió la política real ("30 días desde la recepción", returns #233) y dejó la fila en `resolution_events` (billing #234). Comando: `railway run bash -c 'psql "$DATABASE_URL" -f <migración>'` — comillas SIMPLES para que la var la expanda Railway, no tu shell (si no: `database "lider" does not exist`).
- **🔴 PENDIENTE en PRODUCCIÓN:** cuando `develop` pase a `main`, aplicar a prod **las dos de arriba** + `add_gorgias_channel` (esta antes de que Gorgias salga en vivo allí). Lo aplicado arriba es **solo staging**.

**Pendientes (orden sugerido):**
1. **🔴/🟠 Backlog de la auditoría de robustez (de la s71, #231).** El hallazgo 🔴 L3-sin-approval ya está cerrado y mergeado. Quedan: **#2 race de concurrencia** — no hay lock por conversación; la idempotencia es por `message_id` (Chatwoot/Gorgias), así que 2 mensajes distintos del mismo cliente casi a la vez corren `process_inbound` en paralelo sobre el mismo state (sin checkpointer) → fix sugerido: advisory lock por `(tenant_id, conversation_id)`. **#3 entrega outbound best-effort** — `respond` marca `resolved` + cierra el ticket externo aunque `send_outbound` falle (cliente sin respuesta, ticket cerrado); fix: no marcar resuelto/cerrar hasta confirmar entrega. Menor: `get_tool_permissions` en `db/queries.py` es código muerto (sin callers).
2. **🟠 Zendesk — verificación E2E en vivo** (CÓDIGO listo, [#232] mergeado: dual-auth API token/Basic + provider `zendesk` en `configure_staging_integrations`). Falta: crear API token en un Zendesk sandbox → `railway run … configure_staging_integrations --tenant marea-studio --only zendesk` (con la `INTEGRATIONS_SECRET_KEY` de staging, o InvalidTag/500) → configurar el Trigger→Webhook → probar resolución/cierre/reapertura/escalado. Confirmar el outbound (`add_comment` público) contra la API real, como se hizo con Gorgias. (El enum `channel_type` ya tenía `zendesk` → sin migración.)
3. **🟡 Latencia — cerrar en vivo** (PROMPT listo, [#233] mergeado: el AOP `returns` verifica la política ANTES de afirmar plazos → mata el reject+retry del supervisor). Falta: `railway run -- … seed_canonical_aops --update` para que **Marea** herede el AOP nuevo → **curar `tenant_facts` de Marea** con la política de devoluciones (`return_window_days`, etc.) para que el agente la lea inyectada y se ahorre hasta el `get_shop_policies` → medir hops antes/después con `railway logs -d | grep llm_call` + traces. (Rollout de `smalltalk` a Lunaria/Purigu **descartado**: son simuladores, no aporta.)
4. **🟡 Billing — activar** (MOTOR listo, [#234] mergeado: `resolution_events` + conteo con ventana §2.3 + tiers + `GET /usage` + `PUT /subscription` + hooks). Falta: aplicar la migración (ver arriba) → crear la suscripción de cada tenant real (`PUT /billing/subscription` super_admin, o `upsert_billing_subscription`; sin ella `GET /usage` da 404 honesto) → **Stripe = siguiente trozo de código** (subscription=suelo, metered=overage + webhook; necesita `STRIPE_API_KEY` + productos/precios en su dashboard) → medir **COGS real** en LangSmith antes de fijar el overage (€0,20 vs €0,25; ancla €0,071 s64).
5. **🧭 Customer Discovery (foco estratégico, regla dura).** El [`market-analysis-2026-06.md`](market-analysis-2026-06.md) recomienda **bifurcar en 2 cohortes**: 5 e-commerce escenario 4 (quemados de Gorgias/Permut/GuruSup) + 5 comercializadoras de energía independientes (driver Ley 10/2025, deadline 28-dic-2026). NO pivotar; el dato decide. Pendientes de verificación antes de pitch: texto art. 2 Ley 10/2025, cliente Mundimoto↔Permut (sin fuente pública).

**Hecho en sesión 72 (autónoma, 3 PRs MERGEADOS, suite 1306 verde):** ~~Zendesk E2E (código)~~ ✅ [#232] dual-auth API token/Basic (espejo de Gorgias) + provider `zendesk` en configure (el enum ya tenía zendesk → sin migración; outbound shape estándar) — falta E2E en vivo (punto 2); ~~Latencia HOPS (prompt)~~ ✅ [#233] el AOP returns secuencia "verificar antes de afirmar" → mata el reject+retry — falta re-seed Marea + curar facts + medir (punto 3); ~~Billing Bloque 2 (motor)~~ ✅ [#234] resolution_events + conteo con ventana §2.3 + tiers + endpoint + hooks — Stripe + aplicar migración + crear suscripciones = manual (punto 4). Rollout `smalltalk` descartado (simuladores). **Post-merge:** las 2 migraciones nuevas aplicadas a staging y el flujo completo verificado EN VIVO sobre Marea (turno de devoluciones: `respond` sin error → política real → `resolution_event` creado).
**Hecho en sesión 71:** ~~Re-auditoría de robustez del grafo~~ ✅ + ~~hallazgo 🔴 L3-sin-approval cerrado~~ ✅ (PR1 piso `_l3_requires_human_approval` + migración `l3_autonomy_acknowledged_at/_by` NULL=fail-safe + propagación al state; PR2 endpoint 422 sin `acknowledge_l3_autonomy` + `upsert` sella/limpia). 1297 verde. **Falta:** correr la migración en staging + PR a develop. Backlog auditoría #2/#3 abierto (ver punto 0).
**Hecho en sesión 70:** ~~Latencia palanca HOPS~~ ✅ 3 palancas, 2 PRs validados en vivo: [#228] P1 (cache del retry: `reason#3` ahora `cache_r=2986`, antes 0) + P2 (criterio del supervisor); [#229] P3 (no supervisar lecturas L1: turno de devoluciones 7→6 hops, confirmado con traces antes/después). Hallazgo de método: la palanca real (P3) se vio en el trace, no era P2.
**Hecho en sesión 69:** ~~Verificar Gorgias E2E~~ ✅ punta a punta (Basic auth [#223]; 3 bugs cazados: enum `channel` + [#224] outbound `source.type`/mirror + [#226] `body_html` email vacío; resolución+reapertura+escalado por plazo verificados en vivo); ~~CLAUDE.md modelos Fable/Opus/Sonnet~~ ✅; [#225] docs.
**Hecho en sesión 68:** ~~4 hallazgos 🟠 de la auditoría~~ ✅ [#218]/[#219]; ~~latencia palanca concisión (a)~~ ✅ [#220] (267-293 tok vs 476); ~~router Haiku (c)~~ ✅ [#220]+[#221] (1,7s vs 3,5s en charla, vía AOP `smalltalk`); ~~medir todo en vivo~~ ✅.
**Hecho en sesión 67:** ~~Auditoría del grafo~~ ✅; ~~instrumentación latencia/cache~~ ✅ [#213]; ~~señales residuales~~ ✅ [#214]; ~~handle_error → helpdesk~~ ✅ [#215]; ~~classifier resiliente~~ ✅ [#216].
**Hecho en sesión 66:** ~~Formato Markdown chat~~ ✅ [#210]; ~~prompt caching (palanca #1)~~ ✅ [#211].

**Nota latencia (b, descartado en s68):** "menos tool hops vía KB/facts" NO se atacó como código del grafo — es curación de AOPs/facts per-tenant; queda dentro de la palanca de HOPS (punto 3) y del dogfood.

**Deuda previa aún viva:** fixtures de eval huérfanas (slugs legacy ≠ canónicos; `smalltalk` tampoco tiene fixture de eval aún); **chip vivo:** persistir `refresh_token` en el OAuth de Gorgias (`oauth_gorgias.py` lo descarta → la integración OAuth se cae al caducar); ticket de prueba 66116601 (Marea Gorgias) quedó `open` — residuo del debugging, cerrar a mano; README no existe en develop (si se quiere logo, crear uno nuevo SIN "BPO" — contradice el posicionamiento de CLAUDE.md).

---

## ✅ Fix #5 intent-switch continuity-aware — HECHO (sesión 60)

**Rama:** `fix/intent-switch-continuity` (desde `develop`, con #164 + #165 ya mergeados). **Modelo:** Opus.

**El problema (verificado en sesión 59):** el grafo NO usa checkpointer y `process_inbound` arma el state desde cero cada mensaje → `aop_slug` nacía vacío → el clasificador corría cada turno pero **CIEGO**. Riesgo: flapping mid-procedimiento en respuestas cortas/ambiguas ("el azul", "12345").

**El fix aplicado:**
1. `select_aop` carga el AOP previo desde `intent_classifier_runs` con `get_last_intent_for_conversation` (ya existía; sin migración ni checkpointer).
2. Lo inyecta en el prompt del clasificador → **continuidad a nivel LLM** (juzga si el pivote tiene sentido y devuelve conf alta cuando sí).
3. **Histéresis determinista** en `_resolve_aop_slug` (red de seguridad): continuidad (mismo slug) / salir-de-`default`-fácil (basta `min_confidence`) / pivote-confiable (≥ `intent_switch_threshold=0.70`, setting nuevo) / si nada aplica → mantiene el previo (anti-flapping).
4. Borrado el scaffolding muerto (`_should_reclassify`, `aop_locked_until_turn`, `aop_completed_signal`). `was_reclassification` ahora se infiere de DB.
5. Desambiguación por pregunta: **diferida** (la continuidad ya hace seguro el split returns/refunds). `pending_intent` se conserva como reservado.

**Edge cases cubiertos:** AOP previo desactivado a mitad de conversación → se trata como primer turno; slug inválido con conf alta + hay previo → mantiene el previo (no salta a default).

**Verificación:** suite **1143 verde** (matriz pura de histéresis de 10 casos + integración), ruff clean, 0 mypy nuevos.

**Esto cierra los 5/5 fixes de grafo del 10/10.** Diseño completo en `docs/aop-canonical-design.md`.

**Diferido** (capa opcional del fix de fecha #4): `days_since_order` calculado en código para que el LLM no reste fechas.

**Próximo paso técnico:** mergear este PR → con los 8 AOPs canónicos + 5/5 fixes de grafo listos, queda desbloqueado el dogfood E2E con la "tienda ligera" de Lunaria (correr la 25/25 con judge — ver Bloque 0.11).

---

## 🐕 Dogfood E2E Marea — L1 + L3 verificados ✅ (sesiones 60→62)

Target del dogfood: **Marea Studio** (`683246c2-10ce-4f6c-a299-5053f32f8c01`, slug `marea-studio`) — completa (KB 8 chunks+embeddings, facts, 8 AOPs canónicos, Shopify + Chatwoot, 11 tool permissions). Pedido real de pruebas: **#1181** (`order_id` interno `7133866033432`).

**✅ L1 / routing (sesión 60):** Fix #5 multi-turno (shipping→returns→refunds, continuity-aware sin flapping); `order_status` sobre #1181 (L1 success, sin invención); returns/refunds responden política sin escalar; **Chatwoot real E2E** (widget → `/webhooks/chatwoot` → marea-studio → skill → respuesta en el widget).

**✅ L3 con approval (sesión 62) — cerrado E2E:** `order_change` → `update_shipping_address` sobre #1181, vía **widget Chatwoot real**. Cadena completa: gate (no ejecuta, crea `pending_approval`, avisa al cliente) → aprobación desde dashboard → **ejecución real contra Shopify** → confirmación natural al cliente → **revert** a la dirección original. `complaint` también verificado (empatía + recoge contexto + escala con razón, sin L3, sin promesas). El camino de aprobación **nunca había funcionado**; lo abrió este dogfood.

### Hallazgos del dogfood

| # | Hallazgo | Estado |
|---|---|---|
| H1 | Provisioning no crea `tenant_configurations` ni prompt base → tenant nuevo falla 1er mensaje | ✅ [#171](https://github.com/Auyan-ai/platform/pull/171) |
| H2 | Política anclada solo en `get_shop_policies` (returns/refunds escalaban) | ✅ [#168](https://github.com/Auyan-ai/platform/pull/168) |
| H3 | access_token Shopify cacheado en claro en DB | ✅ [#169](https://github.com/Auyan-ai/platform/pull/169) |
| H4 | `returns` calcula plazo desde `created_at`, no desde la recepción (más estricto que la política) | ⏳ chip |
| H5 | Colisión `account_id` cross-tenant en webhook (`LIMIT 1` sin unicidad) | ✅ [#172](https://github.com/Auyan-ai/platform/pull/172) — índice único parcial + fail-closed |
| H6 | Cierre por inactividad no sincroniza `resolved` al helpdesk + verificar entrega del nudge | ⏳ chip |

### Bugs del flujo L3 (sesión 62 — el approve estaba roto de raíz)

| Bug | Qué | PR |
|---|---|---|
| A | 500 al aprobar: `SkillContext` con kwargs obsoletos (`shopify_domain/token`) → `TypeError`. Helper `services/commerce_context.build_commerce_integration_ctx` (creds de `tenant_integrations` + token exchange) | ✅ [#173](https://github.com/Auyan-ai/platform/pull/173) |
| B1 | El dashboard interno (`(dashboard)/layout.tsx`) solo validaba sesión, no `super_admin` → un `tenant_admin` podía renderizarlo. **No** es fuga de datos (la API aísla: `get_tenant_id` da 403), pero sí frontera de operador rota | ✅ [#174](https://github.com/Auyan-ai/platform/pull/174) |
| B | 500: mensaje `agent_human` sin `author_user_id` (viola `messages_human_has_author`), en approve **y** reject | ✅ [#175](https://github.com/Auyan-ai/platform/pull/175) |
| C | 422 Shopify: `country` en texto libre ("España") no soportado → `country_code` ISO (`_country_to_iso2`, ES-first + fallback) | ✅ [#176](https://github.com/Auyan-ai/platform/pull/176) |
| D | Mensaje al cliente = volcado crudo del output (slug + dict) → redactado con **Haiku** (`services/approval_reply`, fallback plantilla) | ✅ [#177](https://github.com/Auyan-ai/platform/pull/177) |
| E | Los mensajes del flujo L3 (escalate "en revisión" + confirmación al aprobar) **no llegaban al cliente** en el widget. E1: webhooks solo entregaban en `respond`. E2: approve/reject no despachaban al helpdesk (`services/helpdesk_delivery`) | ⏳ [#178](https://github.com/Auyan-ai/platform/pull/178) ABIERTO |

**Decisión de producto (quién aprueba L3):** ambos roles, cada uno desde su dashboard — `tenant_admin` los suyos vía `/clients`, `super_admin` vía el dashboard interno. La API ya aísla por tenant, así que **no** se añade `require_role` al router de approvals. (Auto-graduación de skills a automático y self-service de AOPs = roadmap.)

**Operativo:** página de prueba del widget en `apps/api/scripts/chatwoot_widget_test.html` (websiteToken de Purigu; **sin commitear**). Servirla con `python3 -m http.server 8899 --directory apps/api/scripts` → `http://localhost:8899/chatwoot_widget_test.html`.

### 🌅 Arranque (sesión 63)
- **Modelo:** Sonnet para los chips acotados; Opus si toca diseño (país determinista / observabilidad).
- **Verificar primero:** mergear **#178** → forzar deploy de `platform` si no firea (ver [[reference_railway_deploy_trigger]]) → re-probar L3 desde el widget: deben llegar el "en revisión" y la confirmación de Haiku.
- **Chips pendientes (por prioridad sugerida):**
  1. **País determinista** — hoy el LLM rellena `country` (puso "Spain" solo); para tienda solo-España no debe depender del LLM. Opción A: preservar el país del pedido actual; opción B: default del tenant. Importante porque clientes reales omiten el país.
  2. **H4** — plazo de devolución desde la recepción, no `created_at` (+ dato en facts).
  3. **H6** — sync de cierre por inactividad → helpdesk + entrega del nudge (relacionado con #178/E2).
  4. **Observabilidad:** la ejecución del L3 al aprobar no deja fila en `skill_audit_log` (solo queda el gate como `rejected_by_permissions`).
  5. **PII:** la dirección de envío no se redacta en `pending_approvals.inputs_redacted`.
  6. **Limpieza:** dead code `isDashboardRoute` en `middleware.ts`; retrofitear `load_tenant_context` al helper `build_commerce_integration_ctx`; `REPLY_MODEL` (Haiku) constante → promover a setting + multi-idioma en `approval_reply`.

---

## Empezar aquí

**Modelo recomendado:** Sonnet.

**Rama actual esperada:** `develop`.

**Estado general:**

| Área | Estado |
|---|---|
| Bloque 0 | 0.1–0.10 completados. 0.11 reencuadrado como Agent Verification Staging. |
| Bloque 1 | 1.0–1.9 completados y archivados. 1.10 billing manual tiene runbook, pero depende de inputs externos por cliente. |
| Staging DB | Migraciones de Bloque 1 aplicadas; ya no bloquean la validación. |
| Siguiente paso | **Customer Discovery** sigue como foco estratégico (sesión paralela). En el track técnico: validar magic link visual de Fase 1 (espera rate limit + fix Site URL) → arrancar **Fase 2** del onboarding (portal del cliente con doc upload + Shopify token paste + helpdesk OAuth). Corrida simulator 25/25 queda relegada. |
| Reciente en develop | #131 recalibró pricing, #132 agent skills, #133 Chatwoot HMAC + simulator reseed, #134/#135 docs, #136 guardrail anti-invención, **#137 provisioning productizado (Fase 1)**. |
| Sistema de onboarding | Plan completo cerrado vía /grill-me: ver `docs/onboarding-system-plan.md`. Fase 1 ✅ mergeada (provisioning + magic link + UI). Fases 2-4 pendientes (portal cliente, Shopify content import + starter AOPs, lifecycle gates). |
| Chatwoot staging | ✅ Integración real registrada en Lunaria (cuenta `Purigu`, `account_id 167723`) + webhook → `/webhooks/chatwoot`. ✅ **Smoke test e2e PASÓ** (conv `99386d3b`): consulta de pedido #1003 resuelta con skill Shopify L1 sobre datos reales, traza en LangSmith. |

---

## Foco actual — Customer Discovery (sesión 53)

**Diagnóstico:** ~75k líneas, ~90% del stack, **0 clientes reales** entrevistados. Lunaria es simulador, no cliente. La ansiedad por la competencia (Sierra, Decagon, Permut, GuruSup, ElevenLabs) es síntoma: el diferenciador de Auyan no es la calidad del agente (table-stakes en 2026), es la **operación gestionada** del agente para el segmento.

**Regla dura:** no tocar el agente hasta mandar 3 mensajes de descubrimiento. Interés ≠ demanda.

**Objetivo de la semana:** 10 marcas ICP → 3 mensajes → 3 conversaciones.

**ICP Starter:** Shopify España, 2,5–5 M€ facturación, 500–1.000 tickets/mes, ≥1 persona cuyo trabajo sea CX (filtro duro). Dos cohortes a partes iguales — **ya-usa-bot** (Gorgias AI / Tidio / Intercom Fin / Zendesk AI) vs **no-bot**; el contraste ES el mapa de mercado.

Plan completo en [`docs/customer-discovery.md`](customer-discovery.md): reencuadre, mensaje de outreach verbatim, formulario de 9 preguntas, e hipótesis testeables de pricing / wedge / GTM.

**En marcha (otro chat):** construir `docs/discovery-targets.md` con 10 marcas reales (no inventar datos) usando herramientas €0 (Store Leads, Wappalyzer, view-source, Trustpilot, LinkedIn).

**Seguridad:** repo `Auyan-ai/platform` ahora **privado** (antes público con docs de estrategia expuestos, 0 forks). `.gitignore` no borra historia ya commiteada — privado es el fix limpio.

---

## Sistema de onboarding productizado — Fase 1 cerrada

**Plan completo:** [`docs/onboarding-system-plan.md`](onboarding-system-plan.md) (cerrado vía /grill-me sesión 56). Modelo: managed por invitación (no signup público), 4 fases, dogfood en tienda Shopify real (Marea Studio).

**Fase 1 — Provisioning (mergeado [PR #137](https://github.com/Auyan-ai/platform/pull/137)):**

- Migración `plan_tier` (`founding`/`standard`/`trial`) — semilla para futuro tier trial diferido.
- Service `tenant_provisioning` que usa `supabase_service_role_key` (antes sin uso) → invite vía Supabase Admin + crea `tenants` + `public.users` + `tenant_onboarding` + `tenant_assignment` en transacción + lifecycle `initial→discovery`.
- Endpoint `POST /tenants` (super_admin only) + UI "Nuevo cliente" en dashboard (botón en `ReviewQueueHome`).
- 11 tests nuevos (5 service + 6 endpoint). 865 tests pasan, sin regresiones.
- Verificado en staging: tenant **Marea Studio** (`marea-studio`) creado desde la UI, lifecycle `discovery`, invite generado con JWT real. Plumbing funciona.

**Pendiente Fase 1 (mañana, 2026-06-01):**

1. Fix **Supabase staging Site URL** = `https://auyan-web-staging.up.railway.app` + Redirect URLs.
2. Esperar 1h por rate limit del built-in email Supabase (~4/h).
3. "Send magic link" desde Authentication → Users → kennyrmv@gmail.com.
4. Validar visualmente: click → portal de onboarding del tenant Marea Studio carga bien.

**Próximas fases (planificadas):**

- **Fase 2:** portal del cliente — wizard extendido con doc upload (reuso `pending_review`), Shopify token paste, Chatwoot token + auto-webhook, OAuth buttons Gorgias/Zendesk. Lifecycle auto `discovery→building` por checklist.
- **Fase 3:** Shopify content auto-import (pages/blogs/articles → markdown → `pending_review`) + starter pack AOPs e-commerce ES clonado al provisionar.
- **Fase 4:** dogfood end-to-end completo en Marea Studio + simulator 25/25.

---

## Bloque 1 — Sprint A en progreso

### Completado y archivado

| Sub-PR | Foco | Estado |
|---|---|---|
| 1.0 | Design Sprint + shell Mercury light | ✅ Archivado |
| 1.1 | `tenant_playbook` | ✅ Archivado |
| 1.2 | `tenant_facts` | ✅ Archivado |
| 1.3 | Onboarding wizard + lifecycle | ✅ [PR #102](https://github.com/Auyan-ai/platform/pull/102), QA manual aprobado |
| 1.4 | KB drop-zone + pending review | ✅ Archivado |
| 1.5 | Reporte semanal + aprobación + Postmark + cron | ✅ [PR #104](https://github.com/Auyan-ai/platform/pull/104)–[#107](https://github.com/Auyan-ai/platform/pull/107) |
| 1.6 | Dashboard cliente 7 secciones MVP | ✅ [PR #109](https://github.com/Auyan-ai/platform/pull/109)–[#113](https://github.com/Auyan-ai/platform/pull/113) |
| 1.7 | Review Queue interna cross-tenant | ✅ [PR #115](https://github.com/Auyan-ai/platform/pull/115) |
| 1.8 | Landing pública `apps/landing` + Plausible | ✅ [PR #117](https://github.com/Auyan-ai/platform/pull/117) |
| 1.9 | Email outbound general: templates + queue + retry + UI | ✅ [PR #119](https://github.com/Auyan-ai/platform/pull/119)–[#121](https://github.com/Auyan-ai/platform/pull/121) |

### Sub-PR 1.10 — Billing manual primeros clientes

**Objetivo:** cerrar operación manual de cobro para los primeros 1–2 clientes antes de abrir Stripe/Billing técnico en Bloque 2.

Estado: runbook creado; bloqueado por inputs externos por cliente. No es el foco activo mientras se prioriza la verificación del agente.

Runbook base:

- [`docs/billing-manual.md`](billing-manual.md) — política Founding Partner, tiers, checklist por cliente y flujo factura + transferencia.

Faltan inputs externos por cliente:

1. Definir precio final acordado por cliente y responsable comercial.
2. Confirmar datos fiscales y destinatario de facturación.
3. Confirmar contacto operativo y fecha de inicio de servicio.
4. Registrar factura manual enviada y estado de cobro fuera del producto.

### Nota viva — Shopify content import / KB bootstrap

Idea recomendada para reducir fricción de onboarding: importar contenido existente de Shopify al pipeline de KB.

Investigación inicial con docs oficiales Shopify:

- Shopify Admin API expone pages/blogs/articles con HTML de contenido estático.
- Puede detectar páginas relevantes: `faq`, `devoluciones`, `envíos`, `garantía`, `contacto`, `privacy`, `terms`.
- No reemplaza el drop-zone: muchas FAQs viven en theme, apps, metafields/metaobjects o páginas externas.

Spike sugerido:

1. Listar pages/blogs/articles.
2. Detectar títulos relevantes.
3. Convertir HTML a texto/markdown.
4. Mostrar preview en cola `pending_review`.

---

## Pendientes vivos

### Deuda — Onboarding portal (Fase 2)

| Deuda | Severidad | Notas |
|---|---|---|
| Step 7 (Legal) pide aceptar DPA + Términos + GDPR sin links a documentos reales | media | El cliente acepta cláusulas que no puede leer. Bloquea cumplimiento real. Crear `apps/web/app/(public)/legal/{dpa,terms,privacy}/page.tsx` con contenido legal + linkearlos desde los checkboxes del step. |
| Step 9 (Confirmación) deuda: si el lifecycle no avanza a `building` al darle "Enviar", el cliente queda atascado sin saber qué falta | media | El portal debe mostrar el checklist remanente con CTAs a cada step incompleto. Hoy parpadea y no redirige porque el server-side layout vuelve a mandar a `/onboarding`. (Resuelto en PR #147.) |
| Step 6 (KB) solo acepta texto pegado o URL | **alta** | Cliente real tiene FAQs en PDF, políticas en Word, screenshots de procesos, hojas Excel, notas en `.md`. Hoy debe copy-paste manual. Implementar upload de: PDF, DOCX, DOC, TXT, MD, RTF, PNG/JPG/WebP (vision para extracción), XLSX/CSV (tablas). Pipeline: upload a Supabase Storage → worker extrae texto (Anthropic Files API o textract según tipo) → crea `tenant_knowledge_submission` con `original_filename` + `metadata.extracted_from` → flujo de aprobación normal. Cap por archivo (10 MB) + total por tenant (configurable). |
| Imágenes laterales KREA pendientes (steps 4, 5, 6, 8) | baja | Mientras tanto se ve un placeholder dashed. No bloquea funcionalidad. Prompts ya documentados en gstack/designs/. |

### Bloque 0.11 — Agent Verification Staging

Objetivo: verificar que el agente funciona correctamente en condiciones cercanas a vida real, sin depender de datos inventados y con LangSmith como fuente primaria de observabilidad.

Alcance reencuadrado:

1. Integrar LangSmith en staging para trazas de conversación, grafo, nodos, decisiones, skills, coste y errores.
2. Optimizar simulator: Sonnet como judge default, Opus opcional, corrida normal con tope de coste de `$5`.
3. Crear fixture realista de tenant: playbook, facts, onboarding, KB, AOPs, tool permissions e integraciones.
4. Preparar Shopify test store con órdenes reales marcadas `auyan-e2e`; no aceptar verificación formal sobre datos inventados.
5. Probar primero `/webhooks/inbound` y luego Chatwoot real como primer helpdesk.
6. Medir alineación entre propuesta del agente y decisión humana para decidir cuándo una skill puede pasar a automático por tenant.

Criterios de aceptación iniciales:

- 25/25 scenarios pasan critical assertions sin judge.
- Sample con judge Sonnet obtiene promedio mínimo `8/10`.
- 0 acciones L3 ejecutadas sin aprobación.
- 0 tracking/refunds/orders inventados.
- Corrida normal bajo `$5`.
- 100% de runs visibles en LangSmith con correlación a DB.

Tenant de prueba Lunaria staging: `11111111-1111-1111-1111-111111111111`.

Resultado corrida 25/25 + fix anti-invención (sesión actual):

- **Fase A (sin judge, 25/25):** ✅ todas las assertions críticas pasan. Criterio #1 cumplido.
- **Fase B (judge Sonnet):** promedio `7.28/10` — **bajo el `≥8.0`** del criterio #2. Coste `$1.3936` (bajo `$5`, criterio #5 ✅). EX-01 con WARNING es intencional (mock error). 0 L3 sin approval (#3 ✅), 0 tracking/refunds inventados (#4 ✅), 100% en LangSmith correlacionado a DB (#6 ✅).
- **Hallazgo raíz del 7.28:** con KB vacía y AOPs sin verificar, el agente **alucinaba datos blandos sin respaldo** — DE-01 inventaba un plazo de envío; RE-02/RE-07 inferían política de devolución cuando `get_shop_policies` devolvía vacío. Es un problema de **comportamiento/guardrail**, separable del **contenido** (KB/AOPs reales), que se difiere al onboarding del primer cliente.
- **Fix aplicado (`aops/compiler.py`):** reforzado `_render_global_rules` — la **única** regla anti-invención incondicional del system prompt (el bloque de KB sólo aparece si hay chunks). Ahora prohíbe afirmar plazos/fechas/políticas/importes sin respaldo y manda tratar tool vacío/error como dato no disponible. Test nuevo en `tests/test_aop_compiler.py`; suite del compiler **63/63 verde**.
- **Verificación barata (3 escenarios, judge Sonnet, ~`$0.13`):** el fix **cambia el comportamiento**. DE-01 dejó de inventar y ahora **escala honestamente** (la assertion `response_contains.días` ahora falla = ya no inventa; judge `4.2→3.0` porque el judge premia dar respuesta y castiga la honestidad cuando no hay contenido). RE-02 estable (`6.8`; el "30 días" viene del AOP, no inventado → 3/3 assertions pasan). RE-07 `8.0→8.2`.
- **Lectura:** el guardrail es **quirúrgico** — suprime lo no respaldado (DE-01) pero no lo respaldado por el AOP (RE-02 sigue diciendo "30 días"). El **judge no puede validar guardrails sobre KB vacía** porque mide contenido, no comportamiento. **Criterio #2 (judge ≥8) queda bloqueado por CONTENIDO real** (KB + AOPs verificados en onboarding), no por comportamiento. Guardrails anti-alucinación: **listos para el primer cliente**.
- **Estado: ⏳ esperando la "tienda ligera" de Lunaria para correr la última prueba 25/25 con judge.** El fix anti-invención sale en PR aparte contra `develop`. La tienda ligera (la arma Kenny) = contenido mínimo en DB que los 25 scenarios ya asumen, **sin** tocar el grafo:
  - **`tenant_facts`:** `return_window_days: 30`, `shipping_info` (estándar 3-5 días hábiles · express 1-2 · gratis > $50), `business_hours`, `support_email`/`support_phone`/`website_url` (para escalar con contexto honesto).
  - **KB (`knowledge_base_chunks` con embeddings, vía `seed_kb`):** doc de **envíos** (DE-01, CE-02/05), doc de **devoluciones** (30 días + digital no retornable; RE-01/02/05), doc de **garantía** (DE-02 — *hoy no está en ningún mock, el agente no tiene de dónde sacarlo*). **Dejar sin documentar a propósito** los temas que prueban escalar-cuando-no-sé (EX-02 cambio de color, DE-03 fuera de alcance): si se documentan, esos scenarios dejan de escalar y rompen su assertion.
  - **3 AOPs a verificar/redactar** (los scenarios fuerzan estos slugs): `consulta_envio` (CE-*, EX-01/03), `returns` (RE-*), `default` (DE-*, EX-02/04) — cada uno con allowed_skills correctos, procedimiento por caso, guardrails y escalation_triggers.
  - **Ya OK (no crear):** datos de pedido/tracking/producto/refund vienen de **mocks por scenario**; integración Shopify registrada; tiers `refund_partial`/`cancel_order` = L3.

Estado LangSmith staging:

- ✅ [PR #127](https://github.com/Auyan-ai/platform/pull/127): LangSmith como observabilidad primaria del agente; Langfuse queda como espejo opcional.
- ✅ [PR #128](https://github.com/Auyan-ai/platform/pull/128): `LANGSMITH_WORKSPACE_ID`, endpoint EU, `trace_id/dotted_order` y child `agent_model_call` tipo `llm` para tokens/coste nativos.
- ✅ Railway staging configurado con `LANGSMITH_ENDPOINT=https://eu.api.smith.langchain.com`, workspace `bd943bb5-40a8-4178-a15c-71d473fca472` y proyecto `auyan-staging`.
- ✅ Webhooks reales validados en LangSmith: `agent_conversation` muestra input/output/decisión/confianza; `agent_model_call` muestra `input_tokens`, `output_tokens`, `total_tokens` y `total_cost`.

Pendiente futuro, sólo cuando haga falta más granularidad:

- Crear sub-runs internos por paso del grafo: `load_tenant_context`, `select_aop`, `retrieve_knowledge`, `reason`, `supervise`, `execute_skill`, `respond`/`escalate`.
- Enriquecer cada sub-run con AOP seleccionado, chunks recuperados, tool calls, approvals y errores, manteniendo cuidado de no exponer secretos ni PII innecesaria.

### Staging / servicios externos

| Pendiente | Estado |
|---|---|
| LangSmith | ✅ Validado en staging EU: traces reales en `auyan-staging`, root `agent_conversation` + child `agent_model_call` con tokens/coste nativos. Sub-runs internos por nodo quedan como mejora futura. |
| Simulator | Optimizado: Sonnet judge por defecto, Opus opcional, cap `$5/día` por tenant. #133 añadió reseed de user profiles y modo sin-judge en `_compute_status`. ✅ Corrida 25/25 contra Lunaria ejecutada: Fase A 25/25 críticas; Fase B judge `7.28/10` (bajo `≥8.0` por KB vacía, no por comportamiento — ver subsección 0.11). |
| Shopify test store | ✅ Tres órdenes reales `auyan-e2e` creadas en Lunaria: `#1001` (`CE-NO-TRACKING`, sin tracking), `#1002` (`CE-TRACKING`, tracking `1Z999AA10123456784`) y `#1003` (`RETURNS-IN-WINDOW`, tracking `1Z999AA10123456785`). ✅ Shopify registrado como integración primaria `commerce/shopify` en `tenant_integrations` con credentials cifradas. |
| Chatwoot Cloud | ✅ **Smoke test e2e PASÓ** (conv `99386d3b`, 2026-05-30). Cadena verificada: widget → webhook `200` → HMAC de #133 validada contra Chatwoot real → AOP `consulta_envio` → `shopify.get_order_status` (L1, success, 493ms) sobre el pedido real #1003 → respuesta en Chatwoot + dashboard → 4 runs `agent_conversation` en LangSmith con tokens/coste, correlacionadas a Supabase por tags `tenant`/`channel:chatwoot`. Integración registrada vía `configure_staging_integrations.py` (cuenta `Purigu`, `account_id 167723`). ⚠️ **Gota operativa:** las credenciales deben cifrarse con la `INTEGRATIONS_SECRET_KEY` de staging — registrar siempre vía `railway run ... configure_staging_integrations`, no en local (si no → `InvalidTag`/500 al desencriptar en el server). |
| Gorgias OAuth app | Sigue pendiente; se implementará después de Chatwoot. |
| Zendesk OAuth app | Sigue pendiente; se implementará después de Chatwoot. |
| Postmark | Falta `POSTMARK_API_TOKEN`, `POSTMARK_FROM_EMAIL` y **dominio `auyan.ai` aún no comprado** → DKIM/SPF bloqueado. Workaround Sender Signature con single email se descartó por estética (invite saliendo desde `kennyrmv@gmail.com`). Esperar a tener dominio para hacer setup completo + plug como SMTP de Supabase (saca rate limit del built-in). |
| Supabase Auth staging | Pendiente: **Site URL** = `https://auyan-web-staging.up.railway.app` (hoy apunta a `localhost:3000`, rompe magic links). + añadir a Redirect URLs. Bloquea validación visual del magic link de Fase 1. |
| Weekly Reports cron | Falta setear `DATABASE_URL` en GitHub Actions para el workflow programado. |

---

## Deuda no prioritaria — Landing launch polish (2026-06-08)

No mover esto a "Siguiente paso" mientras Customer Discovery + onboarding sigan mandando. Esta deuda no bloquea el PR actual ni el lanzamiento exploratorio de la landing.

| Deuda | Prioridad | Nota |
|---|---|---|
| Captura real de leads | baja por ahora | La landing puede salir con CTAs a correo/calendario. Luego decidir entre Tally/Typeform/Calendly o formulario propio conectado a CRM. |
| Eventos de analytics | baja | Añadir eventos para CTAs principales, pricing, Founding Partner y sign in cuando tengamos dominio/analytics final. |
| Legal mínimo público | media-baja | Privacy, Terms, Cookies y DPA antes de campañas más amplias o tráfico pagado. |
| Favicon, OG social y marca final | baja | Pulir favicon/logo final, preview social y assets de share cuando el dominio esté comprado. |
| QA post-deploy | baja | Canary visual y smoke test en producción después de montar dominio/env vars. |
| Blog real o navegación sin blog | baja | La landing ya referencia blog; publicar al menos una pieza SEO o esconderlo hasta tener contenido útil. |
| Páginas long-tail SEO | baja | Más adelante: alternativas/competidores y casos tipo `gorgias-ai-alternative`, `zendesk-ai-shopify`, `managed-ai-customer-support`. |

---

## Referencias rápidas

- [`docs/progress-archive.md`](progress-archive.md) — historial completo.
- [`docs/customer-discovery.md`](customer-discovery.md) — plan de descubrimiento de clientes (sesión 53).
- [`docs/billing-manual.md`](billing-manual.md) — pricing, tiers, ICP y billing manual.
- [`docs/auyan-master-context.md`](auyan-master-context.md) — fuente única de verdad negocio + producto.
- [`docs/architecture-agent-v2.md`](architecture-agent-v2.md) — arquitectura técnica del agente.
- [`docs/architecture-web.md`](architecture-web.md) — arquitectura dashboard web.
- [`docs/DESIGN.md`](DESIGN.md) — sistema visual vigente.
- `CLAUDE.md` — reglas operativas del proyecto.
