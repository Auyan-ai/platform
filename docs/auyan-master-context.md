# Auyan — Contexto Maestro

> Fuente única de verdad del proyecto. Documento vivo, versionado en git.
> Última actualización: 2026-07-17 (§9: unidad de cobro = resolución, decisión sesión 64).
> Versión: 2.1 (post-pivot)

---

## Cómo usar este documento en chats nuevos

Al arrancar cualquier chat técnico o estratégico de Auyan, este archivo es el primer punto de referencia. Captura quién es Kenny, el modelo de negocio post-pivot, las decisiones arquitectónicas tomadas hasta hoy y el plan de construcción.

Convive con:
- `docs/architecture-agent-v2.md` — detalle técnico de la arquitectura del agente
- `docs/progress.md` — bitácora de sprints terminados y próximo paso operativo
- `CLAUDE.md` (raíz) — reglas operativas del proyecto que sobreescriben default behavior de Claude

Cuando haya conflicto entre este documento y otros, este manda en lo conceptual; los otros mandan en lo técnico específico.

---

## ÍNDICE

1. Quién es Kenny
2. Preferencias de comunicación
3. El pivot estratégico (BPO → Managed AI)
4. Tesis y modelo de negocio
5. Filosofía operativa
6. ICP (cliente ideal)
7. Competencia y diferenciación
8. Producto y propuesta de valor
9. Pricing
10. Modelo operativo (entrega del servicio)
11. Stack técnico
12. Arquitectura del producto (decisiones del grill-me)
13. Estructura legal y fiscal
14. Captación de clientes
15. Métricas y validación
16. Riesgos
17. Roadmap 12 meses
18. Plan de construcción técnica (Bloques 0-3)
19. Decisiones cerradas del grill-me
20. Glosario

---

## 1. Quién es Kenny

- **Co-founder operando bajo filosofía Rocket Internet + Jensen Huang**: velocidad de la luz, pero sobre verdad, no sobre ejecución ciega.
- **Inmigrante en España**, sin red local de founders.
- **Capital disponible**: 20-50K€ (vida cubierta aparte).
- **Tiempo**: full-time.
- **Skill core**: marketing/growth + Claude Code + generalista.
- **Experiencia sectorial**: 6 años en atención al cliente DIGI (telco español), primero como agente, luego como gestor postventa. Conoce el sector CX desde dentro.
- **Esposa**: también ex-DIGI, 6 años como agente equipo digital. Co-founder operativa. **Su rol bajo el pivot**: QA + Knowledge Management + Customer Success (ya NO atiende tickets BPO).
- **Objetivo**: exit 1-5M€ en 3-5 años. No lifestyle, no unicornio.

---

## 2. Preferencias de comunicación

### Cómo hablarle
- **Idioma**: español venezolano neutro. Tutea siempre (tú, tienes, puedes), nunca vosees (nada de vos, tenés, podés, andá). Evitar palabras de México, Argentina, España o Centroamérica. Ni "malandro" ni "sifrino".
- **Honestidad brutal**: dar contexto cuando está equivocado. No seguir la corriente. Cuestionar decisiones cuando se vea riesgo.
- **No asumir sin preguntar**.
- **Antes de responder preguntas con componente temporal**, buscar la fecha actual.
- **Separación de chats**: cada chat tiene una fase específica.
- **Formato**: tablas, listas y diagramas cuando aplique. Sin emojis salvo que él los use primero.
- **Sparring estratégico**, no vendedor.

### Cómo asistirle
1. Sparring estratégico antes que ejecución ciega.
2. Stress test de suposiciones — no asumir que números son correctos.
3. Investigación con web search antes de afirmaciones factuales.
4. Cuestionar calibración de ICP si menciona marca grande o ajena al ICP.
5. Recordar capital limitado — no sugerir quemar dinero antes de validar.
6. Pensar en ventana competitiva: GuruSup levantó €1.3M abril 2026, Permut activo. 12-18 meses antes de que decidan subir a managed.

### Lo que NO quiere
- Que lo traten como cliente al que vender. Es founder, dale realidad.
- Que reescriban la estrategia cada vez sin cuestionarlo.
- Bullets infinitos cuando una tabla o párrafo funciona mejor.
- Felicitaciones por preguntas obvias.

---

## 3. El pivot estratégico (decisión 2026-05-22)

### Modelo descartado
**BPO con agentes humanos** atendiendo tickets propios de Auyan para escalados. Bottleneck operacional. Margen 30-40%. No escala sin contratar mucho. Esposa no quiere atender tickets 8h/día.

### Modelo elegido
**Managed AI service estilo Crescendo "Managed AI" tier**, a escala SMB+ y mid-market low-end español. Configuramos, mantenemos y optimizamos el agente IA del cliente. El cliente mantiene **su propio equipo de soporte humano** para escalados; nosotros somos su equipo externo de **Agent Engineers**.

### La frase definitoria
> "Somos tu equipo externo de Agent Engineers. Tu equipo de soporte se queda. Nosotros construimos, mantenemos y mejoramos cada semana el agente IA que reduce su carga 60-70%. Ni configuras nada, ni gestionas créditos, ni inventas qué optimizar. Reportamos semanalmente con propuestas concretas. Tú apruebas o rechazas."

### Posicionamiento clave (cerrado en grill)
**Servicio managed con control plane propio: producto Decagon/Sierra (uso interno) + entrega Crescendo (cliente)**.

- Internamente Auyan opera con power tools tipo Duet/Agent Studio: editor pleno de AOPs, simulator con user profiles, auto-generación de AOPs desde transcripts, auto-tests, diagnostic tools, watchtower-style QA.
- El cliente experimenta el modelo Crescendo: dashboard read-only + reportes proactivos + AIDE asignado humano + cero configuración técnica.
- Auyan puede usar ElevenLabs, helpdesks, modelos u otras plataformas como infraestructura cuando convenga. La defensibilidad no está en poseer cada runtime, sino en el control plane operativo propio: AOPs, simulator, approvals, QA, audit, playbooks, reports y mejora semanal.
- La analogía estratégica: **Sierra/Decagon para SMB+ y mid-market low-end español que no tiene acceso a equipos técnicos**, entregado como servicio managed.

---

## 4. Tesis y modelo de negocio

### Las tres olas del CX

- **Ola 1**: servicios → SaaS (Zendesk clásico).
- **Ola 2**: SaaS → copilotos IA (Intercom Fin, Decagon, Gorgias AI Agent).
- **Ola 3 (2025+)**: copiloto → servicio AI-native (Sierra, Crescendo, 14.ai). El cliente paga por tener resuelto el problema, no por herramienta.

**Auyan está en Ola 3, modelo Crescendo Managed AI, a escala SMB+ y mid-market low-end español.**

### Por qué este modelo y no otros

| Descartado | Por qué no |
|---|---|
| BPO con humanos | Margen bajo, no escala, esposa no quiere |
| SaaS self-serve (Permut, GuruSup, Chatbase) | Ventaja injusta vale cero. Race to the bottom |
| Implementador puro encima de ElevenLabs/Gorgias/etc. | Captura poco valor, fácil de saltar por el cliente, defensibilidad baja |
| Sierra enterprise | Cliente target requiere $200K+/año + 400 empleados |
| **Managed AI a la Crescendo SMB+ español** ✅ | Hueco vacío. Ventaja injusta aplica. Margen 80%. Stack 90% ya construido |

### Diferenciación específica

1. **Conocimiento sectorial real** (6 años DIGI + esposa ex-DIGI).
2. **Equipo dedicado pequeño** (no 200 agentes rotando para 30 marcas).
3. **IA con brand voice del cliente** (prompts entrenados con emails reales).
4. **Español nativo** (no filipino con acento, no inglés traducido).
5. **Founder técnico + operativo** (Kenny construye, esposa QA-KM).
6. **Stack ya construido al 90%**: Skills L1/L2/L3, AOPs versionados, supervisor pattern, slow agent con LLM-as-judge, audit log GDPR-ready.

### Ventana competitiva

- **Crescendo** $91M ARR aterrizó UK abril 2026. Mid-market enterprise. No habla español nativo, no toca SMB+.
- **Sierra/Decagon** enterprise USA. No bajan a SMB+ EU en 12-24 meses.
- **14.ai** $3M YC marzo 2026. Mismo modelo, USA.
- **ElevenLabs / ElevenAgents**: empezó Conversational AI el 2024-12-03; agregó Chat Mode el 2025-08-19; renombró a ElevenLabs Agents el 2025-09-03; lanzó ElevenAgents for Support el 2026-02-17. Competidor fuerte en plataforma de agentes voz/chat y posible proveedor futuro de voz. No debe ser tratado como enemigo principal de Auyan mientras Auyan compita en operación managed, e-commerce español, QA, shadow mode, activación por categoría y reportes semanales.
- **GuruSup** €1.3M seed abril 2026 (4Founders Capital). Founder ex-GuruWalk. SaaS self-serve.
- **Permut Inc** (Barcelona) SaaS self-serve.

**Ventana real: 12-18 meses para clavar PMF en SMB+ español antes que GuruSup/Permut decidan subir tier, ElevenLabs empaquete servicios managed por vertical, o gigantes USA bajen.**

### Métricas año 1 objetivo

- 25-30 clientes activos
- MRR €40-60K
- Equipo 2-3 personas (Kenny + esposa + 1 AIDE junior contratado mes 10-12)
- Caja acumulada €60-100K
- Posicionamiento consolidado en e-commerce SMB+ español

---

## 5. Filosofía operativa

- **Velocidad de la luz** (Jensen Huang) sobre verdad.
- **Do things that don't scale** (Paul Graham) los primeros 3 meses: Kenny + esposa hacen onboarding profundo personalmente.
- **Productización extrema** (Rocket Internet) desde el inicio: no consultoría a medida, servicio repetible.
- **Foco brutal** en un nicho hasta dominarlo.

### Filtro brutal de 7 preguntas (aplicado al modelo nuevo, todas verde)

| # | Pregunta | Resultado |
|---|---|---|
| 1 | Madurez modelo USA | 🟢 Crescendo $91M, Sierra $150M+, Decagon $35M |
| 2 | Tiempo del modelo | 🟢 Sweet spot 2-3 años |
| 3 | Gap en España | 🟢 Nadie en managed AI service SMB+ |
| 4 | TAM España | 🟢 30-50K e-commerce activos, capturando 0.5-1% = €3-15M ARR |
| 5 | Capital validación | 🟢 <2K€ + MVP construido (90%) + margen 80% desde cliente 1 |
| 6 | Ventaja injusta | 🟢🟢 Marketing/growth + Claude Code + 6 años DIGI + esposa + stack 90% |
| 7 | Exit potencial | 🟢 6-12M€ a €2M ARR, dentro del rango |

---

## 6. ICP (Ideal Customer Profile)

**Scale-ups y mid-market low-end españoles con equipo CX existente.**

- E-commerce Shopify (preferido) o WooCommerce
- 20-400 empleados totales
- Equipo CX de 2-30 personas
- 1.000-15.000 tickets/mes
- Presupuesto CX actual: €10-80K/mes
- Founder accesible o Head of CX identificable en LinkedIn
- Pueden estar usando: Gorgias, Zendesk, Intercom, Permut, GuruSup → frustrados por no llegar a >50% resolution rate

**Restricción primeros 5 clientes:** Shopify + helpdesk existente o ya decidido (Gorgias/Zendesk/Intercom/Chatwoot Cloud). No abrir WooCommerce ni marcas sin helpdesk salvo excepción deliberada por aprendizaje comercial muy claro. La meta inicial es caso de estudio limpio, no amplitud de integraciones.

### Ejemplos que SÍ son ICP
Tipo Mundimoto (170 empl, $65M raised, e-commerce motos, ya con Permut), Housfy (317 empl, proptech), Yuxus, Scuffers, BeLevels, Tramas+, OffUgo, Aston Rentals, Reveni, Waynabox.

### Lo que NO es ICP
- SMB pequeño sin equipo CX (founder hace soporte) → Permut/Chatbase
- Enterprise (>500 empleados) → Sierra/Crescendo
- No-Shopify mass scale mes 1-6

### Los 4 escenarios del mercado español

| Escenario | % mercado | ICP? | Comentario |
|---|---|---|---|
| 1. Nada serio (Gmail + WhatsApp) | 40-50% | ❌ | No tiene presupuesto ni dolor suficiente |
| 2. Tidio/Crisp/Tawk básico | 25-30% | 🟡 | Posible si tiene equipo CX |
| 3. Shopify Inbox/Zendesk mal config | 15-20% | 🟡 | Si tienen +3 personas |
| 4. Gorgias/Permut/GuruSup | 5-10% | 🟢 | **ICP prime mes 1-6**. Vienen quemados |

---

## 7. Competencia y diferenciación

### Mapa de capas

| Capa | Tipo | Ejemplos | Relación |
|---|---|---|---|
| L1 | Infra modelos | OpenAI, Anthropic | Proveedor |
| L2 | Frameworks | LangGraph, Voiceflow | Proveedor |
| L3 | SaaS / agent platforms self-serve | Chatbase, Permut, GuruSup, Tidio Lyro, ElevenAgents | Competencia indirecta o proveedor según modalidad |
| **L4** | **Servicio managed** | **Sierra, 14.ai, Crescendo** | **Tu zona** |
| L5 | BPO tradicional | Atento, Konecta | Sustituto en mente del cliente |

### Diferenciación operacional

- **vs Permut/GuruSup**: ellos venden herramienta (cliente configura + mantiene); tú vendes resultado operacional (Auyan configura + opera + reporta).
- **vs Sierra**: ellos enterprise $200K+/año; tú SMB+ €890-5.990/mes. Mercados que no se tocan.
- **vs Crescendo**: ellos USA/UK mid-market; tú España SMB+. Coexisten.
- **vs ElevenLabs/ElevenAgents**: ellos venden plataforma/infra de agentes con voz y chat excelentes. Tú vendes resultado operacional: diagnóstico, implementación, integraciones profundas, QA semanal, shadow mode, activación por categoría y mejora continua. Si conviene, ElevenLabs puede ser proveedor de voz en Bloque 4; no se construye la narrativa pública alrededor de pelearles en voz, latencia o modelos.
- **vs BPOs**: ellos meten humanos; tú reduces necesidad de humanos.
- **vs construir interno**: tarda 6+ meses interno; tú en 30 días con expertise probada.

### Compradores naturales para exit

- BPOs españoles legacy (Atento, Konecta, Comdata)
- AI gigantes USA bajando a EU (Sierra, Decagon, Crescendo, Ada)
- Helpdesks consolidados (Freshworks, Zendesk, Hubspot, Intercom)
- Shopify-ecosystem (Gorgias, Klaviyo PE)
- PE roll-up español (Magnum, Nexxus)

Múltiplos típicos AI services con MRR recurrente: **3-6x revenue. A €2M ARR = 6-12M€ exit**.

---

## 8. Producto y propuesta de valor

### Qué reemplaza
**NO software** y **NO reemplaza al equipo CX completo**. Reduce carga real del equipo existente: lectura/clasificación, búsqueda/matching, comunicación rutinaria y acciones operativas repetibles (consultar pedido, iniciar devolución, actualizar dirección, cancelar bajo política, preparar reembolso bajo approval). Eso puede ser 60-80% del trabajo repetitivo en e-commerce, pero el 20-40% restante (juicio, emoción, excepciones, casos ambiguos) lo sigue haciendo el equipo del cliente.

### Qué gana el cliente
1. **Velocidad brutal**: respuesta en segundos, no horas.
2. **Reducción de carga del equipo CX**: 60-70% menos tickets que tocan humanos.
3. **Operación experta continua**: Auyan optimiza el agente cada semana.
4. **Reportes proactivos con propuestas**: cliente no decide qué optimizar.
5. **Tiempo recuperado del manager CX**: deja de gestionar prompts y configuraciones.

### Framing comercial

No vender como "reemplazamos tu equipo de soporte". Vender como "quitamos carga repetitiva de forma real, incluyendo acciones, para que tu equipo se quede con los casos donde hace falta criterio". El cliente mantiene control, escalados y ownership de CX; Auyan opera la capa repetible con QA, approvals y mejora semanal.

### Canales (vía helpdesk del cliente)
Decisión clave del grill: Auyan **no construye canales directos** (WhatsApp, Instagram, Widget). Se conecta al **helpdesk del cliente** (Gorgias / Zendesk / Chatwoot Cloud / Intercom) y hereda todos los canales del helpdesk:

- Email del cliente
- Widget chat web del cliente
- WhatsApp Business del cliente
- Instagram DM del cliente
- Facebook Messenger, TikTok, etc

Para clientes sin helpdesk: Auyan **recomienda Chatwoot Cloud**. En staging/verificación se usa plan free o sandbox; en cliente real se pasa a plan paid si volumen/features lo requieren. El cliente paga directo a Chatwoot, Auyan solo se conecta. NO self-hosted nuestro.

### Voz / llamadas

Voz **no forma parte del wedge inicial**. No está descartada estratégicamente, pero queda fuera del MVP comercial hasta tener clientes reales, datos de demanda y claridad de go-to-market. La cuña inicial es soporte escrito vía helpdesk existente + Shopify + operación managed. Cuando haya clientes, se decidirá si voz se lanza como expansión, tier adicional o piloto específico; ElevenLabs puede ser proveedor potencial si conviene.

### Integración Shopify (ya construida)
- Lectura: pedidos, productos, clientes, inventario, devoluciones
- Acciones: cancelar pedido, reembolso parcial, actualizar dirección, iniciar devolución
- 11 skills implementadas (5 L1 + 2 L2 + 4 L3)

### El entregable clave: reporte semanal

Cada lunes 8am cliente recibe **email con resumen** (headlines de métricas + 1-2 insights principales) + **link al dashboard** donde vive el detalle completo. Estructura:

```
Auyan Weekly Report — Cliente X
Semana del [fecha]

═══ Métricas headline ═══
Tickets: 487 (+12%) · AI resolvió: 312 (64%) · Escaladas: 175
Tiempo primera respuesta: 47s · CSAT estimado: 4.3/5

═══ Lo que detectamos esta semana ═══
1. Categoría "cambios talla" con 6 errores menores
   → Propuesta: añadir 3 skills nuevos a AOP "size-exchange"
   → Impacto esperado: 45% → 65%

═══ Plan próxima semana ═══
- Implementar 2 skills nuevos (si apruebas)
- Probar prompt v2.4 en devoluciones

[Ver detalles completos en dashboard →]
```

**El reporte semanal es lo que justifica €2.490/mes.** Ningún SaaS lo da. Es trabajo humano experto sobre datos de la AI.

---

## 9. Pricing

> **Estado:** pricing provisional. Los precios y límites siguen sujetos a validación con los primeros Founding Partners, datos reales de volumen, coste LLM y horas humanas post-onboarding. No tratar como definitivo hasta cerrar evidencia comercial.
>
> **Decisión sesión 64 (2026-06):** la unidad de cobro es la **resolución** (cierre sin escalar), con **suelo mensual + overage**, no el ticket plano. COGS real medido: ~€0,071/resolución. Modelo completo y decisiones abiertas en [`billing-resolution-prd.md`](billing-resolution-prd.md); el motor técnico (conteo con ventana de reapertura, tiers, endpoints) ya está mergeado ([#234](https://github.com/Auyan-ai/platform/pull/234)). Los tiers de abajo siguen siendo la envolvente comercial de referencia; los números por resolución los fija el PRD.

### Programa Founding Partner (primeros 5 clientes, mes 1-6)
- Setup gratis
- Mes 1 gratis
- Mes 2-6 a €690/mes (50% off Starter)
- Mes 7+ €890/mes (precio Starter normal)
- A cambio: caso de estudio público + feedback semanal + 30 min call/semana
- Sin permanencia

### Tiers

| Tier | Setup | Mensual | Tickets/mes | Comentarios |
|---|---|---|---|---|
| **Starter** | Gratis | €890 | 1.000 | Cliente típico: 2-4 personas CX, 500-1.000 tk |
| **Growth** (target) | €1.500 | €2.490 | 3.000 | Cliente típico: 4-10 personas CX, 1.500-3K tk |
| **Scale** | €4.000 | €5.990 | 10.000 | Cliente típico: 10-25 personas CX, 3-10K tk |
| **Custom** | Custom | Custom | 10.000+ | Mid-market fuerte; no prometer estándar sin revisar operación y margen |

### Overage
€0.15-0.30/ticket extra dependiendo del tier.

### Outcome guarantee
- Starter: 25% crédito si resolution rate <45% mes 3
- Growth: 40% crédito si <60% mes 6
- Scale: 50% crédito si <70% mes 6 + SLA First Response <2 min

### Comparativa Growth típico (3.000 tk/mes)

| Opción | Coste mensual | Quién optimiza |
|---|---|---|
| Chatbase Pro + 2 agentes internos | €4.860 | Cliente |
| Permut Scale + 2 agentes internos | €5.670 | Cliente reactivo |
| Crescendo Managed AI | ~€7.300 | Crescendo |
| Sierra Agent OS | €20.000+ | Sierra |
| **Auyan Growth** | **€2.490** | **Auyan (proactivo)** |

**Margen contribución Growth: €1.960/mes = 79%**.

### Billing (decisión grill)
- **Cliente 1-2**: manual (factura email + transferencia)
- **Cliente 3+**: Stripe Subscriptions + Stripe Tax + cupón FP

---

## 10. Modelo operativo (entrega del servicio)

### Roles (estructura DB desde día 1)

**Tabla `internal_users`** con role enum: `super_admin`, `aide`, `qa_km`, `ops_manager`, `cs_manager`.

| Rol | Qué hace |
|---|---|
| `super_admin` | Acceso total cross-tenant. Kenny + esposa hasta mes 9-10. |
| `aide` (AI Deployment Engineer) | Construye agente, mantiene AOPs, conecta integraciones, atiende mensajes del cliente. Asignado a N clientes. |
| `qa_km` (QA + Knowledge Management) | Revisa drafts shadow, procesa KB drops, mantiene tenant_playbook. Transversal a todos los clientes. |
| `ops_manager` | Aprueba reports semanales, schedule, financial. No edita técnica. |
| `cs_manager` | Relación comercial, no técnica. |

### Fases del cliente

| Fase | Mes | Equipo | División |
|---|---|---|---|
| Solo founder | 1-6 | Kenny + esposa | Kenny: AIDE + Ops + CSM. Esposa: QA-KM. Ambos super_admin. |
| Validación | 7-9 | Kenny + esposa | Igual, ~20h/sem op con 7-8 clientes |
| Primera contratación | 10-12 | + AIDE junior | Junior toma role AIDE. Kenny → Ops/CSM. Esposa → QA-KM. **Formalización roles**. |
| Escala | 13-18 | + 2-3 personas | 2 AIDEs, 1 QA-KM, Kenny CEO/CSM |

### Onboarding (4 semanas, ~50-65h Auyan/cliente)

**Wizard self-serve de 9 pasos** (45-90 min cliente) + procesamiento async Auyan:

1. Datos básicos del tenant
2. Cuestionario brand voice (~20 preguntas estructuradas)
3. `tenant_facts` (horarios, teléfono, dirección, links)
4. Conectar Shopify (OAuth 1 botón)
5. Conectar helpdesk (Chatwoot primero para validación/no-helpdesk; Gorgias/Zendesk después según cliente)
6. Drop-zone info inicial (emails históricos, PDFs, URLs)
7. DPA + T&C + GDPR consent (firma digital)
8. Call con AIDE opcional (Calendly)
9. Confirmación → fase Building

**Semana 1 — Discovery**: Auyan lee 100 emails históricos + categoriza + Biblia en `tenant_playbook` (DB, no Notion).

**Semana 2 — Build**: AOPs configurados + KB curada + brand voice integrada en prompts.

**Semana 3 — Shadow mode**: agente postea drafts como **internal notes** en helpdesk del cliente. Cliente responde manualmente. Auyan aprende del diff.

**Semana 4 — Activación gradual**: por categoría según concordancia draft vs respuesta humana real.

### Operación normal (mes 2+) — 2-2.5h/cliente/semana

- Lunes (1h): revisar dashboard + identificar top 3 problemas
- Martes-miércoles (1h): revisar propuestas slow agent, aprobar/rechazar
- Jueves (30 min): generar reporte semanal + personalizar
- Viernes (30 min cada 2 sem): call con cliente

### Capacidad operativa esperada
- 10 clientes activos = 20-25h/semana = manejable con Kenny + esposa
- 20 clientes = 40-50h/semana = necesita 1 AIDE junior
- 50 clientes = 4-6 personas total

### El flywheel de conocimiento

Ticket complejo entra → AI sin confianza alta → Escala al equipo del cliente con contexto completo (vía helpdesk) → Cliente resuelve usando su criterio → Su resolución queda registrada → Slow Agent detecta patrón → Propone update al AOP → Auyan aprueba desde dashboard → Próximo ticket similar → AI responde solo con confianza alta.

**Mes 1**: AI resuelve 35-45%, cliente 55-65%.
**Mes 6**: AI 60-70%, cliente 30-40%.
**Mes 12**: AI 75-85%, cliente 15-25%.

**Esto es defensibilidad operativa pura**.

---

## 11. Stack técnico

| Capa | Tecnología |
|---|---|
| Backend | FastAPI (Python 3.12) |
| Frontend | Next.js 15 + TypeScript + Tailwind v4 + shadcn |
| Landing | Next.js 15 + **Aceternity UI** (free, look Sierra/Decagon/Scale AI) + Framer Motion + MDX + ISR + Plausible |
| Base de datos | Supabase (Postgres + pgvector + Auth + RLS) |
| Agente | LangGraph + Claude (Sonnet 4.6 default, Haiku 4.5 intent/user simulator, Opus solo para casos L3/calibración explícita) |
| Embeddings | OpenAI text-embedding-3-small (1536 dims) |
| Observabilidad | LangSmith como fuente primaria de staging/evals; Langfuse como espejo secundario existente |
| Email saliente (Auyan→cliente) | Postmark |
| Helpdesk del cliente | Chatwoot Cloud primero para verificación; Gorgias/Zendesk después; Intercom reactivo |
| Billing (Bloque 2+) | Stripe Subscriptions + Stripe Tax |
| Deploy | Railway |

### Dominios

- `auyan.com` — landing pública
- `app.auyan.com` — dashboard (cliente + super_admin con auth)
- `api.auyan.com` — backend FastAPI

### Lo que ya está construido y sirve al pivot (90% del stack)

- Multi-tenancy con RLS + `tenant_scope` GUC
- Grafo LangGraph 11 nodos + ReAct loop
- Skills L1/L2/L3 con permission gate (11 Shopify implementadas)
- AOPs YAML+Markdown versionados con workspaces staging/production + eval gate 80% (Sprint 7)
- Supervisor pattern Sonnet/Opus por tier (Sprint 8)
- Human approval mode L3 con cola UI completa (Sprint 10)
- Slow Agent con two-step judge (Sonnet→Opus si confidence <0.7) (Sprint 11)
- Agent Reasoning UI con PII masking (Sprint 8)
- Audit log con pseudonimización GDPR-ready (Sprint 9.3)
- Rate limiting + budget gate por tenant (Sub-PRs A.1-A.4)
- Cleanup automático con timeouts por canal
- 1000+ tests, fixtures de eval/simulator y migraciones de Bloque 1 aplicadas en staging

---

## 12. Arquitectura del producto (decisiones grill-me)

### KB — tres niveles (cliente)

| Nivel | Quién | Qué |
|---|---|---|
| 🔴 Nunca | Solo Auyan | Prompts, AOPs, contenido RAG, retrieval config |
| 🟡 Aporta no edita | Cliente → Auyan cura | Documentos, PDFs, URLs, políticas (drop-zone) |
| 🟢 Edita directo | Cliente form plano | `tenant_facts`: horarios, teléfono, dirección, links — NO entra al RAG |

### Adapters por tenant (refactor Bloque 0)

**Patrón**: `MessageProvider` (base) + `HelpdeskProvider` (extends).

```python
class MessageProvider(Protocol):
    async def parse_inbound_webhook(payload) -> InboundMessage
    async def send_outbound(ctx, conversation_ref, content, attachments) -> None

class HelpdeskProvider(MessageProvider, Protocol):
    async def add_internal_note(ctx, ticket_ref, content) -> None
    async def assign_to_human(ctx, ticket_ref, reason) -> None
    async def update_status(ctx, ticket_ref, status) -> None
    async def push_escalation(ctx, conversation, reason, agent_context) -> ExternalTicketRef
```

**Implementaciones MVP**: `ZendeskAdapter`, `ChatwootAdapter`, `GorgiasAdapter` (helpdesk) + `PostmarkEmailAdapter` (canal outbound Auyan→cliente).

**Tabla `tenant_integrations`** con `kind` + `provider` + `credentials_encrypted` + `config`.

### Escalación al equipo del cliente

Mix por tenant configurado en onboarding:
- **Default cuando hay helpdesk**: push al helpdesk con `push_escalation()` (crea ticket o internal note con contexto completo + razón)
- **Fallback sin helpdesk**: email a `notif_email` del tenant vía PostmarkEmailAdapter
- **Refactor schema `escalations`**: ya no `assigned_user_id` interno; ahora `external_ticket_ref` + `external_provider` + `notified_at` + `acknowledged_at`

### Shadow mode

Modelo Sierra/Decagon:
1. Ticket entra al helpdesk del cliente
2. Webhook a Auyan
3. Agente procesa y genera draft
4. Draft se postea como **internal note** en el helpdesk (NO se envía al cliente final)
5. Equipo cliente ve internal note "🤖 Auyan sugiere: [draft]" y responde manualmente
6. Auyan registra diff entre draft y respuesta real → aprendizaje
7. Después de N tickets con alta concordancia por categoría → Auyan propone activar esa categoría
8. Activación **por categoría** (consulta_envio activa antes que devoluciones)
9. El cliente no opera prompts ni reglas, pero la activación automática requiere su aprobación explícita.

### Simulator / Observability

**3 tipos de test**:
- Unit (Sprint 7 eval harness ya cubre)
- Integration (skills + DB)
- Simulation (multi-turn) — Bloque 0 nuevo

**4 dimensiones del LLM-as-judge** (alineadas con Sierra):
- **Reasoning**: ¿siguió el AOP correctamente?
- **Knowledge**: ¿info factualmente correcta sin alucinar?
- **Tools**: ¿llamó skills correctas con inputs correctos?
- **Brand voice**: ¿mantuvo tono y guardrails?

**Tablas nuevas**: `user_profiles`, `simulation_scenarios`, `simulation_runs`.

**Bloques de escalada**:
- Bloque 0 MVP: scenarios manuales + judge 4-dim + UI super_admin
- 0.11A: LangSmith como fuente primaria de observabilidad/evals, Sonnet judge por defecto, Shopify test store con órdenes reales y Chatwoot primero
- Bloque 2: auto-gen personas/scenarios + bulk runner + scheduled nightly + Diagnostic Tools + Watchtower rubrics
- Bloque 3: production A/B + canary deployment (5%→100%) reemplaza shadow puro

### AOPs con steps[] opcional (preparación Bloque 0)

Para habilitar AOP Flow Analysis estilo Decagon en Bloque 2 (drop-off por step), agregar campo opcional `steps[]` al schema de AOP + emitir `step_entered`/`step_completed` events (extiende `agent_reasoning_events`). Costo Bloque 0: medio día. Datos acumulados desde el inicio para usar en Bloque 2.

### Roles internos

Estructura DB lista desde Bloque 0: `internal_users` con role enum + `tenant_assignments` con `assigned_aide_id`/`assigned_qa_id` por cliente. Al inicio Kenny + esposa ambos `super_admin`; formalización en mes 10-12 cuando contraten primer junior.

### Dashboard cliente (7 secciones MVP)

1. **Home** (Overview con KPIs + heatmap + headline reporte semana + lifecycle phase)
2. **Insights** (reemplaza "Conversaciones") — Explorer estilo Decagon: filtros, heatmap timeline, donut intents, drill-down conversación específica con reasoning panel
3. **Reportes** (historial + actual con sección narrativa LLM)
4. **Knowledge Base** (drop-zone + tenant_facts + estado procesamiento)
5. **Aprobaciones** (cola L3 pending)
6. **Onboarding** (solo durante fase initial, auto-hide después)
7. **Configuración** (integraciones conectadas + branding + perfil AIDE asignado)

**Sidebar estilo ChatGPT/Claude**. **AI Data Assistant cliente → Bloque 2**.

### Dashboard super_admin

**Navegación 2 niveles**:
- **Cross-tenant**: Home (review queue), Clientes, Reportes (cola Lunes 8am), Schedule, Adapters & Health
- **Scoped a tenant**: Overview, Lifecycle, Conversations (debug), KB Management, Approvals, AOPs Editor, **Simulator**, Proposals, Playbook

**Home = Review Queue** filtrado por rol:
- Kenny (super_admin) ve todo
- AIDE asignado a N clientes ve solo sus clientes
- QA-KM ve drops + drafts + proposals de todos los clientes transversal
- Ops manager ve solo reportes pendientes + schedule + SLA alerts

### Iteración rápida — qué va a DB editable

| Pieza | Decisión |
|---|---|
| Pasos del wizard onboarding | Hardcoded (PR + redeploy) |
| Preguntas cuestionario brand voice | **DB editable** |
| `tenant_facts` schema | **DB editable** por vertical |
| AOPs | ✅ DB con workspaces (Sprint 7) |
| Tool permissions | ✅ DB granular (Sprint 10) |
| Notification templates (emails) | **DB editable** |
| Report templates | **DB editable + Jinja** |
| Prompts del agente | ✅ Compilados desde AOPs |
| Adapter registry | Code-side |
| Feature flags por tenant | **DB editable** (`tenant_features`) |
| Rubrics custom QA | **DB editable** (Watchtower-style, Bloque 2) |

### Privacidad y seguridad

| Área | Medida | Estado |
|---|---|---|
| Credentials integraciones | `credentials_encrypted` bytea con salt por tenant | Bloque 0 |
| Uploads cliente | `tenant_knowledge_submissions` con texto/URL/archivo textual client-side; PDFs/binarios + Storage quedan para iteración posterior | Bloque 1 completado |
| PII en mensajes | SHA-256 + salt por tenant | ✅ Sprint 9.3 |
| Cross-tenant access | Solo super_admin con MFA + audit log accesos | Reforzar Bloque 0 |
| Trazas de observabilidad | Staging usa LangSmith como fuente primaria y puede trazar datos test/autorizados completos; producción requiere redacción/retención formal antes de activar | 0.11A staging |
| GDPR DPA | Firma digital en onboarding paso 7 | Bloque 1 |
| Right to erasure | Endpoint `DELETE /tenants/me/data` + cron purga 30d | Bloque 1 |
| Servidores | EU (Supabase EU, Railway EU, Postmark EU) | ✅ ya configurado |
| ENS / ISO27001 | Mes 12+ si subes mid-market upper | Backlog |

---

## 13. Estructura legal y fiscal

### Forma jurídica
**Sociedad Limitada (SL)**. Sin debate.

### Costes constitución
- Capital social mínimo: €1
- Notaría: €150-300
- Registro Mercantil: €90-150
- Asesor fiscal montaje: €150-300
- **Total: €400-800**

### Reparto participaciones
Sugerencia: **50/50 entre Kenny y esposa**. Variante 51/49 a favor Kenny si requiere voto de calidad.

### Pacto de socios (CRÍTICO desde día 1)
Cubre: salida, decisiones unanimidad, vesting (4 años cliff 1), no competencia, dividendos. **Coste €300-600 abogado**. NO saltarse.

### Régimen SS
**Administradores SL → autónomos societarios (RETA)**.
- Kenny: ~€100/mes tarifa plana primer año, €310-400/mes segundo
- Esposa: depende del estatus paro (Vía 1/2/3)

### GDPR
**Encargado de tratamiento** bajo GDPR. Cliente es responsable.
- DPA template en onboarding paso 7
- Política de privacidad en web pública
- Servidores EU (ya configurados)
- Cifrado en reposo y tránsito (Supabase default)
- Audit log con pseudonimización (Sprint 9.3 ✅)

### Costes legales año 1

| Concepto | Coste |
|---|---|
| Constitución SL | €500-800 |
| Pacto socios | €300-600 |
| Plantillas legales (DPA, T&C, privacidad) | €400-800 |
| Asesor fiscal mensual (12 meses) | €840-1.440 |
| Cuotas SS Kenny + esposa primer año | €1.200-2.400 |
| **Total** | **€3.240-6.040** |

### Fase 0 LEGAL — acciones inmediatas (en paralelo con Bloque 0 técnico)

1. Decidir vía paro esposa (asesor laboral)
2. Constituir SL
3. Firmar pacto de socios
4. Contratar asesor fiscal mensual
5. Abrir cuenta bancaria SL
6. Comprar plantillas legales o pagar abogado custom (DPA + T&C + Privacy)

---

## 14. Captación de clientes

### Estrategia A: Outreach hiper-personalizado (canal #1 mes 1-3)
- Día 1-3: lista 50 prospects ICP. Fuentes: Trustpilot 1-3⭐ e-commerce ES, customer stories de Permut/GuruSup, LinkedIn Sales Navigator
- Día 4-7: 10/día outreach. LinkedIn DM o email founder/Head of CX (NUNCA "info@"). Referencia problema específico observado.
- Math: 50 outreach × 20% respuesta × 35% cierre = 3-4 demos en 1 semana

### Estrategia B: Comunidades digitales + content founder (paralela)
- LinkedIn 3-4 posts/semana
- Discord/Telegram Shopify ES, grupos LinkedIn
- **Regla**: participar, ayudar, NO vender

### Killer test (vencer dudas)
> "Mándame 3 emails reales de clientes tuyos del último mes (anonimizados). Te respondo en 24h con el copy exacto que mi sistema generaría. Tú comparas con lo que respondió tu equipo. Si mi respuesta es peor, no me llames más."

### Canales por fase

| Mes | Outreach | Comunidades | Content | Ads |
|---|---|---|---|---|
| 1-3 | LinkedIn DM (canal #1) | Activa | LinkedIn slow burn | €0-300 experimental |
| 4-6 | + cold email | Activa | Casos de estudio | €800-1.300 ads |
| 7-9 | + scale | + partnerships | SEO empieza | €2.000-3.000 ads |
| 10-12 | Referencias | + agencias Shopify | SEO inbound | Steady state |

### Stack tools captación (~€150-250/mes)
- LinkedIn Sales Navigator $99/mes
- Apollo/Lemlist $50-100/mes
- Calendly $10/mes
- Loom $15/mes
- Notion (CRM lite) gratis

---

## 15. Métricas y validación

### Producto/Operación

| Métrica | Mes 3 | Mes 6 | Mes 12 |
|---|---|---|---|
| Resolution rate IA | 35-45% | 55-65% | 70-80% |
| First Response Time | <5 min | <2 min | <30s |
| Tickets escalados | 60-65% | 35-45% | 20-30% |
| NPS clientes finales | ≥30 | ≥40 | ≥50 |
| Errores IA (LLM-judge) | <5% | <3% | <2% |

### Comercial

| Métrica | Mes 3 | Mes 6 | Mes 12 |
|---|---|---|---|
| Outreach volume | 50/sem | 100/sem | 150/sem |
| Tasa respuesta | 15-20% | 20-25% | 25-30% |
| Demos | 3-5/mes | 8-12/mes | 20-30/mes |
| Close rate demo→cliente | 15-25% | 25-35% | 30-40% |
| CAC blended | <€1.000 | <€700 | <€500 |
| Inbound % | 0% | 10-20% | 30-50% |

### Negocio

| Métrica | Mes 3 | Mes 6 | Mes 12 |
|---|---|---|---|
| MRR | €1-2K | €8-12K | €40-50K |
| Clientes activos | 2-3 | 7-8 | 28-32 |
| Churn mensual | <10% | <8% | <5% |
| Margen contribución | 50-60% | 65-75% | 75-85% |
| LTV/CAC | n/a | >10x | >30x |

### Las 8 métricas críticas de validación (mes 6)

| # | Criterio | Umbral |
|---|---|---|
| 1 | Clientes pagando full price | ≥ 5 |
| 2 | Retención mes 3 | ≥ 80% |
| 3 | NPS | ≥ 40 |
| 4 | MRR | ≥ €10.000 |
| 5 | Resolution rate IA | ≥ 55% |
| 6 | CAC payback | ≤ 2 meses |
| 7 | Cerrado vía marketing puro | ≥ 1 |
| 8 | Caso de estudio público | ≥ 1 |

**Punto de decisión mes 6**: si valida → Fase 3 escala. Si no → retro brutal + itera 1-2 meses.

---

## 16. Riesgos

### Top riesgos

| Riesgo | Prob (1-5) | Impacto (1-5) | Score | Mitigación principal |
|---|---|---|---|---|
| Resolution rate <50% mes 6 | 3 | 5 | 15 | Eval gate 80% (Sprint 7 ✅), onboarding profundo, LLM-judge desde día 1 |
| Churn >15% mes 3 | 3 | 5 | 15 | Onboarding 30 días check-ins semanales primer mes, NPS día 14/30/60 |
| CAC >€1.500 sostenido | 3 | 5 | 15 | No ads >€500/mes hasta mes 4-5, outreach personalizado mes 1-3 |
| GuruSup/Permut suben a managed <12 meses | 3 | 5 | 15 | Velocidad máxima ejecución, casos de estudio mes 6+, marca founder |
| ElevenLabs empaqueta managed support por vertical o partners ES | 3 | 4 | 12 | No vender "agente de voz/chat"; fijar Auyan como operación managed vertical e-commerce español. Mantener ElevenLabs como proveedor potencial de voz, no como capa estratégica propia. |
| Crescendo baja a SMB+ ES <12 meses | 2 | 5 | 10 | Foco España + vertical e-commerce profundo |
| Kenny burnout | 3 | 4 | 12 | Disciplina horarios, esposa co-founder operativa, calls limitadas |

### Indicadores tempranos de fallo

- Mes 2: 0 demos pese a 50+ outreach
- Mes 3: <30% resolution rate IA
- Mes 3: 1er cliente piloto piensa cancelar
- Mes 4: <2 clientes pagando
- Mes 5: NPS piloto <20

**Indicador positivo (PMF)**: entre mes 3-5 al menos 1 cliente refiere a otro espontáneamente.

---

## 17. Roadmap 12 meses

```
Mes:    0   1   2   3   4   5   6   7   8   9   10  11  12
        │   │   │   │   │   │   │   │   │   │   │   │   │
Fase: [Setup][--MVP+Piloto--][--Validación--][--Aceleración--][---Escala---]
                                  ▲                          ▲
                                  │                          │
                          Punto decisión:                Decisión:
                          ¿valido o itero?               ¿ronda o bootstrap?
Clientes: 0  0   1   2   3   5   7   10  13  17  21  25  30
MRR (€):  0  0   0   1K  2K  4K  7K  12K 18K 25K 33K 40K 50K
Equipo:   2  2   2   2   2   2   2   2   3   3   3   4   4
```

### Fase 0 — Setup (mes 0, en paralelo con Bloque 0 técnico)
SL constituida · Asesor fiscal · Pacto socios · Cuenta bancaria · Decisión paro esposa · Stack Bloque 0 listo · Dominio + branding básico
- Coste: €1.500-2.500

### Fase 1 — Outreach + MVP final (mes 1-3)
**Mes 1**: Bloque 1 técnico (onboarding + reporte + landing) + 30-50 prospects analizados + LinkedIn arranca
**Mes 2**: Primer FP onboarded gratis + Bloque 1 completado
**Mes 3**: 2 FPs + 1 cliente pagando €690 + resolution 35-45%

### Fase 2 — Validación (mes 4-6)
**Mes 4**: 3-4 clientes
**Mes 5**: 5-6 clientes · MRR €5-7K
**Mes 6**: 7-8 clientes · MRR €8-12K · resolution 55-65% · 1er caso de estudio público

### Fase 3 — Aceleración (mes 7-9)
**Mes 7**: 10-12 clientes · marketing pagado €2.500
**Mes 8**: 13-15 clientes · resolution 65-75%
**Mes 9**: 16-20 clientes · MRR €25K · +1 AIDE junior

### Fase 4 — Escala (mes 10-12)
**Mes 10**: 21-23 clientes
**Mes 11**: 24-26 clientes · 2ª contratación posible
**Mes 12**: 28-32 clientes · MRR €40-50K · decisión ronda externa vs bootstrap

---

## 18. Plan de construcción técnica (Bloques 0-3)

### EN PARALELO desde YA
**Fase 0 LEGAL** — 1-2 semanas externas al código.

### Bloque 0 — Sanity check + fundación arquitectónica (3-4 semanas)

| Sub-PR | Qué incluye |
|---|---|
| 0.1 | Hard removal `tenant_agent` (migration SQL + cleanup código + cleanup tests) |
| 0.2 | Framework adapters base (`MessageProvider`, `HelpdeskProvider`, `IntegrationRegistry`, `tenant_integrations` table) |
| 0.3 | Refactor `ShopifyAdapter` (commerce) |
| 0.4 | Refactor `ChatwootAdapter` (helpdesk, completar bidirec) |
| 0.5 | Refactor `ZendeskAdapter` (helpdesk, completar bidirec + OAuth) |
| 0.6 | Nuevo `GorgiasAdapter` (helpdesk, OAuth, desde cero) |
| 0.7 | `PostmarkEmailAdapter` (outbound Auyan→cliente, no customer-facing) |
| 0.8 | Roles internos estructura DB (`internal_users`, `role_permissions`, `tenant_assignments`) |
| 0.9 | AOPs `steps[]` opcional preparación + events `step_entered`/`step_completed` |
| 0.10 | Simulator MVP: tablas, multi-turn runner, LLM-as-judge 4 dims, UI super_admin |
| 0.11 | Validación E2E del sistema actual con simulator + fix bugs descubiertos |

### Bloque 1 — Sprint A: habilita vender (5-7 semanas)

| Sub-PR | Qué incluye |
|---|---|
| 1.0 | **Design Sprint** (1-2 semanas): `DESIGN.md` + refactor componentes shadcn existentes + aplicar a páginas legacy |
| 1.1 | `tenant_playbook` table + queries + UI super_admin editor |
| 1.2 | `tenant_facts` table + form cliente + lectura del agente como contexto estructurado |
| 1.3 | Onboarding wizard self-serve 9 pasos + `agent_lifecycle_state` + comunicaciones email |
| 1.4 | KB drop-zone + cola `tenant_knowledge_submissions` pending review + UI super_admin procesamiento; Storage/PDFs quedan posterior |
| 1.5 | Reporte semanal automatizado: `weekly_reports` table + cron Lunes 6am + UI super_admin aprobación + envío Postmark |
| 1.6 | Dashboard cliente 7 secciones MVP (Home/Insights/Reportes/KB/Aprobaciones/Onboarding/Configuración) |
| 1.7 | Dashboard super_admin con Home/Review Queue + filtros por rol |
| 1.8 | `apps/landing` Next.js + Aceternity UI + páginas (home/pricing/founding-partner/blog/security/about) + Plausible |
| 1.9 | Email outbound general (no solo reportes): templates editables + queue + retry logic |
| 1.10 | (Billing manual primeros 1-2 clientes — no técnico) |

### Bloque 2 — Sprint Duet + Billing + UI pulida (6-8 semanas)

| Sub-PR | Qué incluye |
|---|---|
| 2.1 | Stripe Subscriptions + Stripe Tax + cupón Founding Partner + webhooks + tablas `billing_*` |
| 2.2 | Dashboard cliente: sección Facturación (plan + tickets usados + factura próxima + historial PDFs) |
| 2.3 | Simulator auto-gen: user_profiles desde AOP + scenarios desde KB/transcripts |
| 2.4 | Simulator bulk runner + scheduled nightly + templates de scenarios pre-built |
| 2.5 | Diagnostic Tools: Escalation Drivers + AOP Flow Analysis (drop-off por step) |
| 2.6 | Watchtower: custom rubrics per tenant + scoring continuo de conversaciones reales + alerts |
| 2.7 | AI Data Assistant cliente (Duet for customers): chat conversacional NL sobre métricas |
| 2.8 | Promotion gate robusto: AOP no se promueve hasta pasar unit + integration + sims + rubrics threshold |

### Bloque 3 — Producción A/B + canary + escala (6-8 semanas)

| Sub-PR | Qué incluye |
|---|---|
| 3.1 | `agent_traffic_splits` por (tenant, AOP_version) + lógica de routing en grafo |
| 3.2 | Production A/B: comparar versions con traffic compartido + métricas comparativas (CSAT/deflection/volume) |
| 3.3 | Canary deployment ramp 5%→25%→50%→100% + rollback automático por threshold |
| 3.4 | Overage automation por tickets (Stripe metered billing) |
| 3.5 | Outcome guarantee auto-cálculo + crédito Stripe automático |
| 3.6 | Self-service upgrade/downgrade en dashboard cliente |

### Bloque 4 — Backlog futuro (no sprint asignado)

- Memory cross-conversación (deuda técnica)
- Detección automática alucinaciones (refuerzo slow agent)
- Reapertura conversaciones (`previous_conversation_id`)
- Voz/llamadas
- Intercom adapter (reactivo si cliente lo pide)
- WhatsApp directo via Twilio (solo si cliente sin helpdesk lo pide expresamente)
- Modo proactivo / concierge (carritos abandonados, upsell)

---

## 19. Decisiones cerradas del grill-me (2026-05-22)

| # | Área | Decisión |
|---|---|---|
| 1 | Modelo de negocio | Producto Decagon/Sierra interno + entrega Crescendo cliente |
| 2 | KB | 3 niveles: nunca/aporta/edita factual |
| 3 | Helpdesks | 4 adapters bidireccionales: Gorgias + Chatwoot + Zendesk + (Intercom reactivo) |
| 4 | Canales WhatsApp/IG/Widget | Heredados via helpdesk, NO construidos directamente |
| 5 | Chatwoot Cloud | Free/sandbox para verificación; paid si el cliente real lo necesita; cliente paga directo a Chatwoot |
| 6 | Shadow mode | Internal notes en helpdesk del cliente |
| 7 | Activación gradual | Por categoría, decisión Auyan no cliente |
| 8 | Escalación | Mix por tenant: push helpdesk default, email fallback |
| 9 | Onboarding | 9 pasos self-serve + call con AIDE opcional |
| 10 | "Biblia" del cliente | `tenant_playbook` DB en repo, NO Notion |
| 11 | Reporte semanal | Email = resumen, dashboard = fuente completa, Kenny aprueba lunes 8am al inicio |
| 12 | Dashboard cliente | 7 secciones MVP, "Conversaciones" → "Insights" estilo Decagon Explorer |
| 13 | AI Data Assistant cliente | Bloque 2, NO MVP |
| 14 | Dashboard super_admin | Nav 2 niveles + Home Review Queue filtrado por rol |
| 15 | Roles internos | Estructura DB desde día 1, ambos super_admin hasta mes 9-10 |
| 16 | Simulator | Bloque 0 MVP (manual + judge 4 dims), Bloque 2 auto-gen, Bloque 3 canary |
| 17 | 4 dimensiones judge | Reasoning / Knowledge / Tools / Brand voice |
| 18 | Tipos de test | Unit / Integration / Simulation |
| 19 | AOPs steps[] | Preparación Bloque 0 (datos para Bloque 2 Flow Analysis) |
| 20 | tenant_agent | Hard removal en Bloque 0 |
| 21 | Pricing/billing | Stripe Bloque 2 (no MVP), primer 1-2 clientes manual |
| 22 | Landing | `apps/landing` + Aceternity UI (no Tailwind UI) |
| 23 | Design Sprint | 1-2 semanas al inicio de Bloque 1 |
| 24 | Iteración rápida | DB editable lo que itera con cliente, code-side lo demás |
| 25 | Fase 0 legal | En paralelo con Bloque 0 técnico, arrancar YA |

---

## 20. Glosario

### Términos modelo de negocio
- **AI-native services**: modelo donde no vendes software, vendes el resultado. Ola 3.
- **Managed AI service**: subtipo de Modelo 4. Crescendo "Managed AI" tier sin agentes humanos. Mi modelo.
- **BPO**: Business Process Outsourcing. NO es mi modelo.
- **ElevenLabs / ElevenAgents**: plataforma de agentes voz/chat. Para Auyan es competidor indirecto en plataforma self-serve y proveedor potencial de voz futuro; no es el enemigo principal. La diferenciación de Auyan vive en operación managed vertical, integraciones, QA, shadow mode, activación por categoría y reporte semanal.
- **SMB+**: Small-Medium Business lado alto. Mi ICP.
- **Mid-market**: 50-500 empleados, €5-100M revenue. Mid-market low-end es mi ICP fase 2.
- **AIDE**: AI Deployment Engineer. Rol Crescendo. En Auyan mes 1-12 lo hace Kenny.

### Términos CX
- **CX**: Customer Experience.
- **Helpdesk**: software gestión tickets (Zendesk, Gorgias, Intercom, Chatwoot).
- **Resolution rate**: % tickets resueltos sin escalar. KPI más importante.
- **NPS**: Net Promoter Score 0-10.
- **CSAT**: Customer Satisfaction Score.
- **Brand voice**: tono y personalidad con que una marca habla.

### Términos técnicos
- **LLM**: Large Language Model.
- **RAG**: Retrieval Augmented Generation.
- **AOP**: Agent Operating Procedure. Comportamiento como YAML+Markdown editable runtime.
- **Skill**: acción tipada. L1 (lectura), L2 (escritura reversible), L3 (destructiva/financiera).
- **MessageProvider/HelpdeskProvider**: Protocols de adapters por tenant.
- **Slow Agent**: job batch que analiza conversaciones post-mortem con LLM-as-judge.
- **Supervisor pattern**: Sonnet supervisa L1/L2, Opus supervisa L3.
- **Shadow mode**: agente postea drafts como internal notes, cliente sigue respondiendo manual.
- **Canary deployment**: ramp gradual 5%→100% por categoría reemplaza shadow puro tradicional.
- **Watchtower**: always-on QA con rubrics custom (Decagon style, Bloque 2).
- **Duet**: Decagon's bulk transcript intake + auto-gen AOPs/tools/tests (referencia Bloque 2).

### Términos comerciales
- **CAC**: Customer Acquisition Cost.
- **LTV**: Lifetime Value.
- **MRR/ARR**: Monthly/Annual Recurring Revenue.
- **ARPU**: Average Revenue Per User.
- **Founding Partner**: programa primeros 5 clientes con pricing reducido a cambio de feedback + caso de estudio.

### Términos España legal/fiscal
- **SL**: Sociedad Limitada.
- **RETA**: Régimen Especial Trabajadores Autónomos.
- **Tarifa plana RETA**: ~€100/mes primer año.
- **DPA**: Data Processing Agreement. Contrato GDPR responsable↔encargado.
- **Encargado de tratamiento**: procesa datos por cuenta del responsable. **Auyan es encargado**.
- **Responsable de tratamiento**: decide cómo se procesan los datos. **Cliente es responsable** ante sus usuarios finales.

### Códigos de comunicación
- 🟢 verde · 🟡 amarillo · 🔴 rojo
- **Sweet spot**: zona ideal de operación
- **Ballena**: prospect demasiado grande, no es ICP
- **Modelo 4**: AI-native services puro
- **Modelo Crescendo Managed AI**: modelo específico de Auyan
