# Auditoría de viabilidad — Auyan

**Fecha:** 25 de julio de 2026 (investigación de campo: 24 de julio de 2026)
**Origen:** auditoría comparada Aruma vs Auyan, realizada con nueve investigaciones independientes.
**Regla del encargo:** todo dato de este repositorio entra como hipótesis y se reverifica con fuente externa fechada. Lo no verificable se marca, no se rellena.

**Marcas:** **[V]** verificado con fuente externa · **[E]** estimación con supuestos expuestos · **[H]** hipótesis sin verificar

---

## 1. Estado real del proyecto

### 1.1 Lo construido

| Métrica | Valor |
|---|---|
| Backend | ~55.700 líneas, 246 ficheros Python |
| Dashboard | ~13.800 líneas |
| Migraciones SQL | 32 |
| Tests | ~1.278 |
| Grafo LangGraph | 11 nodos |
| Skills Shopify | 11 (5 L1 + 2 L2 + 4 L3) |

Integraciones verificadas end-to-end contra APIs reales: **Shopify, Chatwoot, Gorgias**. Durante esa verificación se cazaron y corrigieron dos fallos reales, incluida una fuga de token a LangSmith y una acción L3 ejecutada sin aprobación. Zendesk tiene adapter completo, sin probar en vivo.

**No es humo. Es trabajo de ingeniería serio.** Eso hace el diagnóstico más incómodo, no menos.

### 1.2 Lo que no hay

- **Stripe: no existe.** Cero apariciones de `import stripe` en todo el repositorio. El código de facturación es un motor de medición: mide consumo, no cobra.
- **Páginas legales de alta:** no existen.
- **Estado real:** staging / dogfood. `case-study-auyan.md:101` afirma "agente conversacional en producción" — el código y `progress.md` muestran que todo lo verificado ocurre en staging, sin ningún tenant de cliente real.
- Deudas declaradas por el propio repo: sin lock de concurrencia por conversación, entrega outbound best-effort, carga de base de conocimiento solo texto/URL.

### 1.3 Validación comercial: cero

| Evidencia buscada | Resultado |
|---|---|
| `docs/outreach-log.csv` | **Una línea: la cabecera. Cero filas.** |
| Tabla de objetivos en `discovery-targets.md` | Vacía |
| Métricas semanales de `gtm-plan-2026-07.md` | En blanco |
| `customer-discovery.md` | 100% plan e hipótesis: perfiles ICP, guion de mensaje, formulario sin respuestas. **Ninguna entrevista real con nombre y fecha** |
| Clientes de pago | 0 |
| Pilotos | 0 |
| Cartas de intención | 0 |
| Rechazos registrados | 0 (no hay envíos) |
| Tenants existentes | Lunaria (simulador), Marea Studio (tienda propia de pruebas), Purigu (sandbox Chatwoot). **Ningún cliente externo** |

**Y el dato que convierte esto de error en patrón:** el propio `market-analysis-2026-06.md`, de junio de 2026, ya lo diagnosticaba — *"60 PRs de producto y 0 mensajes de outreach"*. El repositorio se auditó a sí mismo, acertó, y el mes siguiente se dedicó a seguir construyendo.

### 1.4 Datos sin fuente

De 30 claims inventariados, **9 no tienen fuente explícita**: pricing de competidores (Sierra 150 k$+, Decagon 35 M$, GuruSup 1,3 M€, Crescendo 91 M$ de ARR), TAM de 30–50 k tiendas, tasas de conversión de outreach del 20%/35%, y el **margen del 79%, que no descuenta las horas humanas del fundador**.

El documento mejor fundado del repositorio es `market-analysis-2026-06.md`, notablemente más riguroso que el resto — aunque contiene un hallazgo que él mismo marca como no verificable ("Mundimoto con Permut al 43%") y lo usa como argumento.

---

## 2. El mercado de agentes CX se está comprimiendo

Hechos con fecha **[V]**:

| Hecho | Fecha | Fuente |
|---|---|---|
| HubSpot baja su Customer Agent de 1,00 $ a **0,50 $** por resolución | 14-abr-2026 | MarTech |
| Zendesk incluye capacidades "agentic" **en todos** los planes Suite/Support (antes add-on de pago) | anuncio 30-mar-2026, despliegue may–jun 2026 | Comunicado oficial Zendesk |
| Chatwoot incluye su agente "Captain" con créditos gratis en todos los planes de pago | vigente jul-2026 | chatwoot.com/pricing |
| Zendesk adquiere Forethought | 11-mar-2026 | Tracxn |
| Sierra levanta 950 M$ a valoración de 15.800 M$ | 4-may-2026 | TechCrunch |
| Decagon levanta 250 M$ a valoración de 4.500 M$ | 28-ene-2026 | Bloomberg |

**Precios de referencia verificados:** Intercom Fin 0,99 $/resolución (plan base 49 $/mes con 50 incluidas); Gorgias 0,90 $/resolución; Salesforce Agentforce 2 $/conversación; Crisp con IA real solo desde 295 €/mes. Rango publicado del mercado: 0,50–2,00 $, con presión hacia 0,30–0,50 $.

**Consecuencia directa:** el agente de soporte de IA está dejando de ser algo que se vende aparte y pasando a ser una casilla ya marcada en la herramienta que el cliente ya paga. **El helpdesk sobre el que Auyan se apoyaría (Chatwoot) ya trae de fábrica lo que Auyan vendería.**

### 2.1 El cliente objetivo

- E-commerce español: **114.800 M€ facturados en 2025** (CNMC, 3-jul-2026) **[V]**, +20,6%.
- **No existe desglose público por tramo de facturación** [NO VERIFICABLE] — el mercado direccionable real no está cuantificado.
- Presupuesto real de software de una tienda mediana: **80–200 €/mes** **[V]**.
- Umbral donde compensa un agente dedicado: **600–1.500 tickets/mes** **[E]**. La mayoría de tiendas españolas no llega.
- Ticket medio de compra en España: 69 €; frecuencia 2,5 compras/mes, la más baja desde 2019.

### 2.2 La capa de servicios

Existe visiblemente en España (Javadex, Upliora, Xpertix, Niebla, Lexialogic), publicita 4.000–12.000 € de implantación + 50–300 €/mes, y **no se ha localizado ni un solo caso con nombre de cliente verificable** — ni reseña pública, ni nota de prensa, ni mención en el LinkedIn del cliente final. Buena parte tiene el patrón de una granja de SEO.

Contexto de riesgo **[V]**: el 74% de los despliegues de IA de soporte se revierten (Sinch, 2026); el 95% de los pilotos de IA generativa no llegan a producción (MIT NANDA); el 42% de empresas abandonó la mayoría de sus iniciativas de IA en 2025, frente al 17% el año anterior (S&P Global).

### 2.3 Diferenciación posible

Lo que no cubren los grandes en España: integración nativa con Correos, SEUR y Packlink (ninguno la publica); normativa española y europea de desistimiento de 14 días y el botón obligatorio desde junio de 2026; Bizum.

**Veredicto sobre la defendibilidad: es un hueco de conocimiento de dominio, no técnico.** Cualquiera con acceso a un LLM y una tarde de prompting lo cierra. Solo es defendible por ser el primero en empaquetarlo bien y por el servicio humano continuo.

---

## 3. Horizonte largo: la categoría que sí interesa

### 3.1 Lo que se confirma

**Sierra admite por escrito que hasta el 23 de julio de 2026 no tenía producto de horizonte largo [V].** Sus casos publicados —Rocket Mortgage, Prudential, Nordstrom, Singtel, Cigna— son, tal como están descritos, **deflection de una sola sesión**. El anuncio de Horizon (jul-2026) presenta el horizonte largo como producto **nuevo**, adquirido con Takeoff. Decagon igual: de ~20 casos publicados, solo Hertz y Valon muestran estado persistente.

> **El mercado confunde deliberadamente "agente" con "chatbot de una sesión". Verificado.**

**Y no es solo enterprise:** Kay.ai vende back-office autónomo a corredurías estadounidenses **de tamaño medio** (JMG Insurance, Johnson Insurance, Elliott Insurance) **[V]**. Decagon tiene entre sus clientes a Fourthwall (~4 M$ de facturación, 101–200 empleados). **Existe precedente de horizonte largo real vendido a mid-market.**

### 3.2 El caso Takeoff, con los números reales

Adquirida por Sierra el **23 de julio de 2026** **[V]**. Términos no publicados.

| Rasgo | Takeoff |
|---|---|
| Equipo | **3 fundadores**, tiempo completo desde el minuto uno |
| Trayectoria | Stripe, Salesforce, Jump Trading, Snorkel AI, Stanford, Columbia, Splunk, Twitter, CrowdStrike |
| Formación | 2 de 3 ingenieros con trabajo previo en IA/infraestructura |
| Capital | 15 M$ de Matrix Partners y Lachy Groom (10-jun-2026) |
| Fundación → adquisición | ~14 meses |
| Modelo de precio | Por resultado; contratos individuales de siete cifras |
| Clientes públicos | **Ninguno con nombre** |
| Procesos | Lending de consumo (5–8 días), coordinación sanitaria, onboarding multi-paso |

Se buscó explícitamente un caso de alguien que entrara en esta categoría en solitario, sin capital y sin red: **no existe evidencia pública de que exista** **[V]**.

### 3.3 El mapa completo de la categoría

La tesis "solo Sierra y quizá Decagon" es **incorrecta** **[V]**. La categoría incluye además: **Kay.ai** (back-office de correduría), **Cytora** y **Sixfold** (suscripción de seguros), **EvenUp** (demandas por lesiones), **Norm AI** (cumplimiento, Serie C de 120 M$ en jun-2026), **Legora** (legal, 550 M$ a 5.550 M$ en abr-2026), **Harvey**, **Artisan** y **11x** (campañas de semanas, contratos de 9–65 k$/año), **Cognition** (1.000 M$ a 25.000 M$ en may-2026), **Pancake** (49 $/mes, el único dirigido a fundadores solos).

**De todo el barrido —horizontal, vertical, internacional y español— ninguna empresa vende hoy un agente de verdadero horizonte multi-día a precio y complejidad de venta accesibles para una empresa de menos de 20 empleados.**

### 3.4 La ingeniería ya no es la barrera [V]

En julio de 2026, checkpointing, reanudación y ejecución durable vienen **de fábrica**:

- **LangGraph** — durable execution documentada, `checkpointer` por `thread`, historial de estado, time travel, human-in-the-loop, tres modos de durabilidad.
- **Temporal** — Serie D de 300 M$ en feb-2026 a valoración de 5.000 M$; integración GA con el Agents SDK de OpenAI desde marzo de 2026.
- **Inngest** — AgentKit con tooling MCP, Serie A de 21 M$.
- **OpenAI AgentKit** — Agent Builder visual + Connector Registry; `Sessions` como memoria persistente.
- **Claude Agent SDK** — sesiones persistidas en disco, reanudables por ID, estado del entorno superviviente entre turnos.

> **Lo difícil ya no es construir el agente que dura semanas. Lo difícil es conectarlo de forma fiable a los sistemas reales del cliente —el 46% de los equipos lo cita como su barrera principal, por encima del modelo y del framework— y quién carga con la responsabilidad cuando falla en la acción 40 de un proceso de dos semanas. Solo el 21,9% de las organizaciones tiene claridad sobre eso.**

Esto tiene una consecuencia estratégica directa: **la ventaja no está en el software, está en asumir el riesgo.** Un servicio gestionado donde el proveedor responde del error vale más que un SaaS de autoservicio — y esa es exactamente la tesis original de Auyan (`adr/0002-managed-ai-service-model.md`), que la evidencia de 2026 respalda.

### 3.5 La distancia entre lo construido y lo deseado

No es distancia de esfuerzo, es de arquitectura:

- El grafo **no usa checkpointer**: reconstruye el estado desde cero en cada mensaje.
- **No hay memoria entre conversaciones** (deuda declarada, sin fecha).
- El horizonte de acción es **un turno de un ticket**.
- Y la ironía decisiva: el modelo de negocio actual **vende como característica** la aprobación humana en cada acción de riesgo. Lo construido está diseñado para ser lo contrario de un agente autónomo de horizonte largo.

Pivotar hacia horizonte largo no es añadir funciones: es rehacer el planteamiento. La buena noticia es que la infraestructura que hace falta ya viene resuelta en LangGraph, que es el framework que el repositorio ya usa.

---

## 4. El caso español que hay que estudiar

**Copilot Gestoría** **[V]** — fundada en 2024, **+50 gestorías clientes** a junio de 2026, **desde 9 €/mes**. Recibe facturas durante el trimestre por email y WhatsApp, extrae datos fiscales con Azure Document Intelligence (>95% de precisión), arma los modelos 303/111/130 y los presenta en la sede electrónica de la AEAT **solo tras aprobación humana explícita**. Cumple la Orden HAC/1177/2024. Sin ronda institucional visible.

Es un proceso multi-día con estado persistente, vendido a clientes pequeños, por un equipo pequeño. **Es la prueba de que el modelo es ejecutable a esta escala.** Y su diseño enseña la lección clave: **el humano aprueba el paso irreversible, y con eso se acota la responsabilidad legal.**

---

## 5. Dónde está el hueco en España

### 5.1 Sectores: abierto o cerrándose

**Se está cerrando** donde hay proveedor dominante bien capitalizado **[V]**: **Sage** despliega agentes en toda su suite durante 2026; **Inmovilla** y **Witei** añaden IA incremental (redacción de anuncios, matching de leads, WhatsApp).

**Sigue abierto** donde el software está fragmentado: clínica dental y estética (solo agencias locales poniendo chatbots de cita), inmobiliaria de agencia pequeña, administración de fincas.

**Automoción — corrección importante:** lo que existe en concesionarios son **asistentes de horizonte corto** (Autologica Sky DMS con "AVA", ARBENTIA con agentes de consulta, Dealcar con IA para anuncios y leads). **No se ha identificado ningún agente de horizonte largo en compraventa de coches, ni cuál es el DMS dominante en España** — ambos NO VERIFICABLE. El proceso largo (reserva → financiación → matriculación → entrega) **está vacío según esta investigación**.

### 5.2 Los tres mejores sectores españoles

| Sector | Tamaño | Riesgo principal |
|---|---|---|
| **1. Administración de fincas y gestión de alquiler de carteras medianas** | ~10.003 empresas del sector, >2 M de comunidades gestionadas **[V]** | **Homming** (proptech española) ya automatiza el ciclo completo de alquiler para carteras medias y grandes; puede bajar de segmento |
| **2. Gestorías y asesorías** | ~82.000 empresas; el sector perdió un 7% en tres años, más de 11.000 despachos cerrados **[V]** | A3 (Wolters Kluwer) y Sage son incumbentes fuertes y ya se mueven |
| **3. Correduría de seguros pequeña y mediana** | Cifra agregada NO VERIFICABLE | Paralelo directo con Kay.ai; Foliume y Fast360 empiezan a moverse |

### 5.3 Las tres razones más fuertes en contra

1. **El incumbente vertical se mueve primero y más barato**, con fechas de 2026, no hipotéticas.
2. **La demanda de la pyme española hoy es de automatización barata y puntual** (5.000–15.000 € + 250–400 €/mes de agencias locales, entrega en 2–4 semanas), no de un producto de agente especializado. Se compite contra "más barato y ya conocido", no contra un vacío.
3. **La pyme española media puede no tener volumen**: el 94,4% de las inmobiliarias españolas tiene dos empleados o menos. El caso de negocio de Kay.ai se sostiene sobre clientes con volumen y valor por caso altos; en España eso solo aparece en gestores de cartera media o grande.

---

## 6. Procesos largos de postventa en e-commerce

Cuatro candidatos dimensionados **[V]**:

| Proceso | Tamaño | ¿Es horizonte largo? | Hueco |
|---|---|---|---|
| **Chargebacks y disputas** | 337 M de casos proyectados en 2026 mundial; coste medio de gestión **128 $** sobre importe medio disputado de **84 $**; el 60% de los comercios deja sin disputar más del 40%; se gana ~33% de las disputadas | **Parcialmente** — Visa bajó la respuesta inicial a 9/18 días y Mastercard el CNP de 45 a 30 días. El horizonte largo real solo aparece en prearbitraje y arbitraje | **Ningún proveedor internacional tiene integración confirmada con Redsys**, la pasarela dominante en España. No existe empresa española especializada |
| **Incidencias de transporte** | 5,5% de tasa de daño reportada; >1.000 M€/año de coste en España; 15,2 M de artículos devueltos por daño | **Sí** — reclamaciones de una a tres semanas con seguimiento | Sin solución específica identificada |
| **Devoluciones** | 13.300 M€/año en España (cierre 2025); tasa del 27–31% en moda y calzado | Medio — plazos legales de 14 días | Muy competido en la parte de atención |
| **Recobro B2B** | Plazo medio de pago **80,5 días**, un 34% por encima del límite legal; 1.957 M€ de coste financiero para pymes en 2025 (CEPYME) | **Sí, el más claramente de horizonte largo** | Sin solución identificada |

**Señal de demanda española [V]:** el Banco de España, en su Memoria de Reclamaciones 2025 (publicada en julio de 2026), señala que el fraude con tarjeta es **el motivo de reclamación bancaria que más crece (+18%)**, con 9.179 expedientes de tarjetas, el 31% del total.

**Riesgos del vertical chargebacks:** (1) la integración banco por banco con Redsys es mucho más cara que enchufarse a una API única tipo Stripe — y la hipótesis más probable de por qué nadie lo ha hecho es que el ARR español no lo compensa; (2) si se toca el flujo de fondos en disputa, puede aplicar PSD2; (3) proveedores existentes cobran 25–40% de lo recuperado (Chargeflow 25%, Chargebacks911 y Midigator 25–40%, Signifyd y Riskified 0,5–1,5% del volumen protegido).

---

## 7. Unit economics

### 7.1 Supuestos

| Variable | Valor | Base |
|---|---|---|
| Precio | 300–800 €/mes + 1.500–3.000 € de implantación | **[E]** anclado en agencias españolas 5.000–15.000 € + 250–400 €/mes **[V]**, Artisan/11x 9–65 k$/año **[V]**, Copilot Gestoría desde 9 €/mes **[V]** |
| Coste variable (inferencia, infraestructura) | 10–20% del ingreso | **[E]** |
| Coste real dominante | Horas del fundador en integración e incidencias | **[E]** |
| Ciclo de venta SMB | 4–12 semanas | **[E]** |
| Churn | 20–30%/año | **[H]** sin dato |

### 7.2 Contribución y techo

- Cliente a 400 €/mes con 80% de margen bruto = **320 €/mes de contribución**.
- LTV a 40 meses ≈ **12.800 €**.
- Equilibrio de herramientas: 2 clientes. Para 4.000 €/mes de ingreso: **10 clientes**.
- **Techo del fundador solo:** cada cliente exige integración manual con sus sistemas. Con 15 h/semana, el límite realista es de **10–15 clientes**, es decir 4.000–6.000 €/mes, antes de necesitar contratar.

### 7.3 Proyección (escenarios, no previsiones)

| | Mes 12 pesimista | Mes 12 base | Mes 24 base | Mes 36 base |
|---|---|---|---|---|
| Clientes de pago | 0–1 | 4 | 12 | 25 (ya con ayuda contratada) |
| MRR | 0–400 € | **~1.600 €** | ~5.000 € | ~11.000 € |
| Margen bruto/mes | ~300 € | ~1.280 € | ~4.000 € | ~8.800 € |

### 7.4 TAM / SAM / SOM (sector: administración de fincas y gestión de alquiler)

| | Cálculo | Potencial |
|---|---|---|
| **TAM España** | ~10.003 empresas × 400 €/mes | **~4 M€/mes** |
| **SAM** (cartera media/grande, ~15%) **[E]** | ~1.500 empresas | **~600 k€/mes** |
| **SOM a 24 meses** **[E]** | 12 clientes | **~5 k€/mes** (0,12% del TAM) |

---

## 8. Cómo elegir qué construir

No importa el número de industrias: **importa que sea una**. Con 15 horas semanales, dos sectores son medio sector cada uno. Criterios, por peso:

1. **¿Es reversible el error?** Es el primero porque es el que puede arruinar. Copilot Gestoría presenta ante la AEAT solo tras aprobación humana explícita, y con eso acota su responsabilidad. Elegir un proceso donde el paso irreversible lo confirme siempre un humano.
2. **¿Cuánto vale un caso?** Cientos o miles de euros. Si el caso vale 3 €, no hay negocio a ningún precio.
3. **¿Está fragmentado el software que ya usan?** Donde hay un Sage o un DMS bien capitalizado, la función llega de serie. Donde hay veinte proveedores pequeños, hay tiempo.
4. **¿Hay acceso al comprador?** El sector correcto al que no se puede llamar vale menos que el sector mediocre donde ya hay agenda.
5. **¿Se puede hacer a mano primero?** Ejecutar el proceso manualmente para dos clientes cobrando. Si a mano no se aguanta, el agente no salva; y si a mano ya pagan, se tiene la especificación exacta.

**Regla de expansión:** no añadir sectores, **añadir procesos al mismo cliente**. Vender el segundo producto a un comprador que ya confía cuesta una fracción de vender el primero a uno nuevo.

---

## 9. El test de tres semanas

Lo que está pendiente desde junio y cuesta unas horas:

**20 mensajes de outreach a e-commerce españoles medianos, con oferta concreta y precio, en tres semanas.** Cero reuniones a las tres semanas → se cierra el capítulo. Una reunión → se reabre.

Si se prefiere probar la versión de horizonte largo, el test es el mismo con otro guion: **un proceso, un sector, diez empresas, antes de escribir una línea de código.**

---

## 10. Lo que sigue sin saberse

Desglose del e-commerce español por tramo de facturación · número de corredurías de seguros en España · número de talleres mecánicos · DMS dominante en concesionarios españoles · nivel real de adopción de IA en administración de fincas · cifras exactas de fraude en pagos de España (el informe EBA/BCE de dic-2025 desglosa por país pero no se pudo extraer) · por qué ningún proveedor internacional ha integrado Redsys.

---

## 11. Veredicto

**Congelar, no borrar.** No hay evidencia de que Auyan esté muerto — nunca ha estado vivo: no hay un solo comprador que lo haya rechazado. Lo que sí está establecido con fechas verificables es que el mercado de soporte CX se comprime, que la venta con SLA choca con una dedicación de 15 h/semana fuera de horario laboral, y que la versión que ilusiona (horizonte largo) es un mercado distinto del que sirve este código y tampoco se ha contrastado con nadie.

**Lo único que puede resucitarlo o enterrarlo es el test de tres semanas.** Cualquier otra cosa —una función más, un dashboard más— no es trabajo sobre Auyan: es aplazamiento.
