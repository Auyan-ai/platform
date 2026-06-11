# Auyan — Análisis de mercado: e-commerce vs. otros verticales (junio 2026)

> Encargo: análisis de los documentos internos del repo (`develop`) + análisis del mercado real de atención al cliente en España, para responder si e-commerce sigue siendo el vertical correcto o si hay industrias con más necesidad donde la IA managed pueda brillar.
> Fecha: 2026-06-10. Investigación: 5 líneas de búsqueda paralelas + verificación cruzada. Las afirmaciones llevan fuente y nivel de confianza. Lo no verificable está marcado.

---

## TL;DR

1. **El dato no respalda "e-commerce está quemado". Respalda otra cosa: el self-serve está comoditizado y el managed está vacío.** Los SaaS convergieron en $0,90-1,00/resolución (Gorgias, Fin, Siena), nadie ofrece tier managed real, Crescendo aterrizó en Europa en abril 2026 pero solo UK y a ~$2.900/mes, y no existe (o no es visible) ninguna agencia española posicionada como "managed AI customer service para e-commerce". Tu hueco sigue existiendo **hoy**.
2. **Tu duda no viene de datos: tienes 0 conversaciones de discovery.** Tu propio `customer-discovery.md` (sesión 53) diagnosticó esto como build-first avoidance. Entre la sesión 53 y la 66 hubo ~60 PRs de producto y 0 mensajes de outreach documentados. La ansiedad por la competencia es el síntoma; la falta de validación es la causa. Eso lo escribiste tú.
3. **Hallazgo nuevo que cambia el tablero: la Ley 10/2025** (BOE 27-dic-2025, cumplimiento obligatorio antes del **28-dic-2026**) obliga a TODAS las empresas de servicios básicos (energía, telco, agua, transporte, postal, financiero) **sin importar tamaño**: 95% de llamadas atendidas en <3 min, derecho a humano, 15 días hábiles para reclamaciones (5 para facturación), auditorías anuales, multas hasta 1M€. Las ~400 comercializadoras de energía y los ~30 OMVs pequeños tienen una bomba de compliance con cuenta atrás de 6 meses y casi cero IA desplegada.
4. **Recomendación: no pivotes. Bifurca el discovery.** Corre el sprint de 10 conversaciones que ya tienes diseñado, pero en dos cohortes: 5 e-commerce escenario 4 (quemados de Gorgias/Permut/GuruSup) + 5 comercializadoras de energía independientes. El dato decide, no la ansiedad. Tercera opción en banco: gestoras de apartamentos turísticos (50-500 unidades).

---

## 1. Análisis de tus documentos

Leído completo: `auyan-master-context.md` (v2.0, 2026-05-29), `customer-discovery.md`, `progress.md` (hasta sesión 66, 2026-06-09), `billing-manual.md`, `billing-resolution-prd.md`, `CLAUDE.md`, `bloque-0-plan.md`, `onboarding-system-plan.md`.

### Lo que está sólido

| Área | Evidencia |
|---|---|
| Producto | Stack ~90%, 1.247 tests verdes, dogfood E2E real (L1 y L3 con approval verificados sobre Chatwoot + Shopify reales), COGS medido €0,071/resolución |
| Tesis | Coherente con el mercado: la categoría managed AI está validada en USA (Crescendo >$100M ARR) y vacía en España (verificado abajo) |
| Pricing | Bien anclado: tu Growth €2.490 vs Crescendo ~$2.900 + $1,25/resolución. Tu PRD de billing por resolución va en la dirección del mercado ($0,90-1,00/resolución es la norma) con ~10x de margen sobre tu COGS |
| Defensas | Audit log GDPR-ready, pseudonimización, servidores EU, supervisor pattern: esto vale poco en e-commerce y vale ORO en verticales regulados (sección 3) |

### Lo que está roto (honestidad brutal)

1. **La regla dura del sprint de discovery se incumplió.** El doc dice: "no tocar el agente hasta haber mandado 3 mensajes de descubrimiento". Desde entonces: sesiones 54-66 = AOPs canónicos, fixes de grafo, dogfood, billing, prompt caching, latencia. Todo bueno. Todo build. Outreach: 0. En `progress.md` Customer Discovery aparece como "foco estratégico paralelo" — es decir, pendiente.
2. **La duda sobre e-commerce no nació de un dato nuevo; tampoco la elección de e-commerce fue con datos.** Ninguno de tus docs contiene una sola conversación con un prospect real. La pregunta "¿e-commerce sí o no?" no se responde con más análisis: se responde con las 10 llamadas que ya diseñaste.
3. **Tu propio master context ya contemplaba el pivote a telco/energéticas como Fase 2 (mes 18-24) por la ventaja DIGI.** Lo que hace este informe es adelantar esa hipótesis a HOY como cohorte de discovery, porque apareció un driver regulatorio con fecha límite (Ley 10/2025) que en mayo no estaba en tus docs.
4. **Tu ventana competitiva (12-18 meses) corre desde mayo. Llevas ~3 semanas de ella construyendo features que ningún cliente pidió** (las pidió Lunaria, que es un simulador).

---

## 2. E-commerce español: veredicto con datos

### Tamaño y crecimiento (no es problema de mercado)

- E-commerce ES facturó >€95.000M en 2024 (+13,1%) y en 2025 creció +18-22% por trimestre: Q1 €25.752M, Q2 €28.346M, Q3 €29.296M ([CNMC](https://www.cnmc.es/prensa/datos-comercio-electronico-3T-2025-20260424)). Confianza alta.
- ~46.204 tiendas Shopify activas en España (oct-2025, +31% interanual; Apparel 27%, Home 10%, Beauty 10%) — vía Store Leads citado por [impulsaecommerce](https://impulsaecommerce.com/shopify-espana/). Confianza media.
- No existe cifra pública fiable del total de tiendas online activas ni de su distribución por facturación. El TAM de tu ICP (tiendas >2,5M€ con equipo CX) sigue sin cuantificar — sale de las llamadas, no de informes.

### La competencia self-serve: convergencia, no race to the bottom

| Player | Pricing (jun-2026) | ¿Managed? | Fuente |
|---|---|---|---|
| Gorgias AI Agent | $0,90-1,00/resolución + helpdesk aparte | No | [gorgias.com](https://www.gorgias.com/blog/ai-agent-pricing) |
| Intercom Fin | $0,99/outcome (mín. 50/mes) | No | [fin.ai/pricing](https://fin.ai/pricing) |
| Siena AI | ~$0,90/conversación (cobra aunque no resuelva) | "Assistance" | [eesel](https://www.eesel.ai/blog/siena-ai-review) |
| Zowie | No público; marketing: $0,25-0,50/resolución IA | No | [getzowie.com](https://getzowie.com/) |
| Tidio Lyro | Add-on desde $39/mes por 100 conv. | No | [tidio.com/pricing](https://www.tidio.com/pricing/) |
| Chatbase | $32-400/mes | No | [chatbase.co/pricing](https://www.chatbase.co/pricing) |
| Zipchat | $49-499/mes por volumen | Onboarding asistido | [zipchat.ai/pricing](https://www.zipchat.ai/pricing) |
| GuruSup | Pay-per-message, seed €1,3M abr-2026, "95% resolución" | No | [gurusup.com](https://gurusup.com/es/soluciones-agentes-ia-empresas/atencion-cliente) |
| Permut | No público (app Shopify con recurrente + uso) | No ("set up in minutes") | [permut.com](https://permut.com/en) |
| Crescendo | ~$2.900/mes + $1,25/resolución; Europa = solo UK desde abr-2026 | **Sí (el único)** | [crescendo.ai](https://www.crescendo.ai/news/crescendo-expands-europe) |

Lecturas:

- **El anclaje de precio es real y te afecta.** A $0,90/resolución, un cliente de 1.000 tickets/mes "ve" ~€900 de coste IA puro. Tu Starter (€890) compite contra eso con operación incluida — defendible pero apretado. Tu Growth/Scale es donde la matemática managed gana claro (3.000 tickets: self-serve real = herramienta + horas del manager; tú = €2.490 flat sin horas del cliente).
- **El hueco managed es real, con evidencia por ausencia:** ninguna de las 10 soluciones ofrece done-for-you completo; ninguna agencia española está posicionada ahí (verificado en 3 búsquedas en español; lo más cercano: eComm360 = BPO humano, Sfera AI = voz genérica). Confianza media.
- **Los bots fallan donde tú operas:** merchants reportan que el patrón de fallo no es el FAQ sino el caso crítico — paquetes perdidos, clientes cabreados, tickets cerrados sin resolver ([Shopify Community](https://community.shopify.com/t/discussion-where-is-ai-customer-support-actually-failing-merchants-and-what-would-make-it-genuinely-useful/629598), reviews G2 de Gorgias/Siena). Y ~40% de las pymes que prueban IA la abandonan por no verle utilidad ([aptie.org](https://aptie.org/noticias-sobre-tendencias/por-que-el-40-de-las-pymes-que-prueban-inteligencia-artificial-no-le-ven-utilidad/), confianza media). Ese abandono ES tu wedge.
- **Nadie audita los resolution rates.** Los "95%" (GuruSup) y "90%+" (Zipchat) son auto-reportados; no existe benchmark independiente. Tu argumento "Mundimoto con Permut al 43%" sigue siendo el argumento correcto. (Ojo: no pude verificar públicamente que Mundimoto sea cliente de Permut — revisa tu fuente antes de usarlo en un pitch.)

**Veredicto e-commerce: la tesis "está comoditizado" es FALSA para tu modelo y VERDADERA para el modelo que no eres.** El riesgo real no es la competencia: es (a) que el cliente escenario-4 no perciba el coste de operar su bot porque "la nómina ya está pagada" — tu propio doc lo identifica como el riesgo nº1 del wedge — y (b) el anclaje de precio en el tier bajo. Ambos se validan con llamadas, no con pivote.

---

## 3. El hallazgo regulatorio: Ley 10/2025 (no estaba en tus docs)

[Ley 10/2025, de 26 de diciembre](https://www.boe.es/buscar/act.php?id=BOE-A-2025-26698), de servicios de atención a la clientela. En vigor desde 28-dic-2025, **plazo de adaptación hasta el 28-dic-2026** — 6 meses desde hoy.

| Aspecto | Detalle | Confianza |
|---|---|---|
| Obligados por tamaño | ≥250 empleados O >€50M facturación O >€43M balance (a nivel grupo) | Media-alta ([KPMG](https://assets.kpmg.com/content/dam/kpmgsites/es/pdf/2026/01/legal-alert-regulacion-servicios-atencion-clientela-ley-10-2025.pdf.coredownload.inline.pdf), [Plana Ventura](https://planaventuragarces.com/a-que-empresas-se-aplica-la-ley-10-2025-sobre-atencion-a-la-clientela/)) |
| Obligados SIN importar tamaño | Servicios básicos de interés general: **agua, gas, electricidad, transporte de pasajeros, postal/paquetería, telecomunicaciones, servicios financieros** | Alta ([Moncloa](https://www.lamoncloa.gob.es/serviciosdeprensa/notasprensa/derechos-sociales-consumo-agenda-2030/paginas/2025/ley-servicios-atencion-al-cliente.aspx)) |
| Teléfono | 95% de llamadas atendidas en <3 min de media; gratuito en servicios básicos | Alta |
| IA/bots | NO se prohíbe la IA; se prohíbe la atención EXCLUSIVA por IA. Derecho a humano formado, en el menú principal, en tiempo real | Alta — **bot de primer nivel + escalado humano rápido es un diseño conforme: exactamente tu arquitectura** |
| Plazos | Reclamaciones: 15 días hábiles. Facturación/cargos indebidos: 5 días. Información de incidencias en servicios básicos: 2h | Alta/media |
| Auditorías | Evaluación de calidad + auditorías anuales por empresas acreditadas | Media ([SGS](https://www.sgs.com/es-es/noticias/2026/03/servicios-de-atencion-a-la-clientela)) |
| Sanciones | Régimen TRLGDCU: hasta €100K graves, hasta €1M muy graves | Media-alta |
| Matiz energía | Una enmienda excluyó a comercializadoras/telcos con cuota <5% de la obligación de call center 24h (el resto de obligaciones aplica). ACIE pidió más exenciones alegando que el coste "expulsa a actores medianos y pequeños" — esa queja pública es en sí misma evidencia de dolor presupuestario | Media ([Demócrata](https://www.democrata.es/actualidad/comision-envia-pleno-ley-atencion-cliente-enmienda-excluye-comercializadoras-luz-gas-telefonia/)) — **verificar texto final** |

Implicaciones directas:

- **Tu ICP e-commerce NO está obligado** (casi ninguna tienda supera 250 empl/€50M). La ley no te ayuda en e-commerce.
- **Una comercializadora de 15 personas SÍ está obligada.** Y hoy no tiene SAC maduro: la CNMC documentó deficiencias estructurales de atención al cliente en 29 comercializadoras (835 actuaciones, 2024) y abrió expedientes que alcanzan a independientes (Holaluz, Octopus) ([CEC](https://portal-cec.consumo.gob.es/en/comunicacion/noticias/2025/cnmc-identifies-deficiencies-customer-service-electricity-and-gas), [Roams](https://roams.es/actualidad/energia/iberdrola-endesa-octopus-y-holaluz-bajo-la-lupa-de-la-cnmc-por-su-trato-a-los-clientes/)).
- **Tu stack ya tiene lo que esta venta necesita:** SLA tracking, escalado a humano con contexto, audit log con pseudonimización, supervisor pattern, servidores EU. En e-commerce eso es "nice to have"; en un obligado por la Ley 10/2025 es el producto. El pitch deja de ser "reduce carga 60-70%" y pasa a ser "cumple los plazos de 15/5 días con registro auditable, sin contratar 3 personas".

---

## 4. Ranking de verticales en España

Datos de dolor documentado por sector (2024-2025):

| Sector | Dolor documentado | Volumen | Fuente |
|---|---|---|---|
| Energía | 968.000 reclamantes a eléctricas + ~388.000 a gasistas (2024); solo ~40% resuelto satisfactoriamente; récord de 7,25M switchings eléctricos (+13%, cada uno genera contactos) | Masivo y creciendo | [CNMC](https://www.cnmc.es/prensa/panel-satisfaccion-servicios-20250509), [CNMC Blog](https://blog.cnmc.es/2025/07/30/record-cambios-comercializador-2024/) |
| Banca | 56.099 reclamaciones BdE 2024, récord en 38 años (+69%) — pero pico coyuntural (gastos hipotecarios) y mercado enterprise | Alto, normalizándose | [BdE](https://www.bde.es/f/webbe/Secciones/Publicaciones/PublicacionesAnuales/MemoriaServicioReclamaciones/24/MSR2024.pdf) |
| Seguros | 14.934 expedientes DGSFP (+11,5%); sector nº1 en facturación de contact center (24% según CEX) | Alto | [DGSFP](https://dgsfp.mineco.gob.es/es/Publicaciones/DocumentosPublicaciones/Memoria%20del%20servicio%20de%20reclamaciones%202024.pdf), [CEX](https://www.asociacioncex.org/actualidad/la-facturacion-del-contact-center-en-2024-cae-un-233-situandose-en-2-359-millones-de-euros/) |
| Telco | 9.638 reclamaciones OAUT 2024, **-29% interanual**; los OMVs ya ganan por buen CX (Pepephone, Simyo los mejores) | Cayendo | [OAUT](https://usuariosteleco.digital.gob.es/DatosInformes/Informe-OAUT-Datos-2024.pdf) |

Contexto del mercado CX: contact center España = €2.359M (-2,33% en 2024), ~100.000 empleados; atención al cliente = 60% del servicio; sectores: Seguros 24%, Banca 17%, Telco 16% ([CEX](https://www.asociacioncex.org/actualidad/la-facturacion-del-contact-center-en-2024-cae-un-233-situandose-en-2-359-millones-de-euros/)). Coste de un teleoperador de entrada 2026: base convenio ~€17.070/año → ~€21.700-22.500 coste empresa (estimación derivada de [tablas BOE 2026](https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-5300)) — tu argumento "te ahorro el 3er agente" sigue vigente.

### Tabla comparativa (scoring honesto para TU caso: 2 personas, 20-50K€, stack texto-first, sin voz)

| Vertical | Dolor | Presupuesto €890-2.490/mes | Competencia IA | Accesible outreach | Fit stack actual | Driver regulatorio | Veredicto |
|---|---|---|---|---|---|---|---|
| E-commerce escenario 4 | 🟡 medio (no validado por ti) | 🟢 probado (ya pagan Gorgias+agentes) | 🔴 self-serve denso / 🟢 managed vacío | 🟢 alta | 🟢🟢 90% construido | ❌ no aplica | **Mantener y validar** |
| Comercializadoras energía independientes | 🟢🟢 el más documentado de España | 🟢 la queja de ACIE por costes lo implica | 🟢 casi cero (solo Madrileña RdG/Agentforce, que es distribuidora) | 🟢 empresas jóvenes, LinkedIn activo | 🟡 email/web sí; teléfono no (gap voz); integración no estándar | 🟢🟢 deadline 28-dic-2026 | **Cohorte discovery YA** |
| Gestoras apartamentos turísticos (50-500 uds) | 🟢 24/7, multiidioma, volumen por construcción | 🟢 probable (gestoras cobran ~18% comisión) | 🟢 sin player dominante de CX-IA | 🟢 sector joven, ferias | 🟢 texto/WhatsApp-first; 🟡 requiere adapter PMS (Avantio/Guesty) y multiidioma (rompe tu regla ES-only, técnicamente trivial) | 🟡 NRUA consolida el sector hacia tu ICP | **Banco / 3ª opción** |
| Corredurías de seguros | 🟢 alto | 🟡 solo top ~400-500 con plantilla | 🔴 ya hay verticalizados (Foliume, Tubot, Servinform) + canal AETMA cerrado | 🟡 decisor mayor, poco LinkedIn | 🟡 | 🟢 parcial | No primero |
| Fintech | 🟡 | 🟡 universo pequeño (427 fintech, mayoría <50 empl) | 🟡 | 🟢 | 🟢 | 🟢 SAC obligatorio (ECO/734/2004 + Ley 10/2025) | Oportunista |
| OMVs/telco | 🟡 cayendo (-29%) | 🟡 | 🟢 vacío | 🟢 pero ~30 cuentas TOTALES | 🟢 tu dominio DIGI | 🟢 | Demasiado pequeño como vertical; 2-3 cuentas oportunistas |
| Clínicas (dental/estética) | 🟢 llamadas perdidas | 🔴 low-end comoditizado €49-250/mes (Telqi, Nova GPG, Minute Call); solo cadenas 5-30 centros (~30-80 grupos) | 🔴 Clinicalia ya ocupa el híbrido managed | 🟢 | 🔴 es VOZ, no texto | ❌ | Descartar (sin voz) |
| Administradores de fincas | 🟢🟢 queja nº1 del sector | 🟡 ASP bajo (pagan 20-60€/comunidad/mes) | 🔴 4+ startups nativas 2025-26 (Ciudadela, IAFinkas, CIAX, Fynkus) | 🟢 | 🔴 voz + integración Gesfincas/IESA | ❌ | Descartar |
| Logística/última milla | 🟢 WISMO | 🟡 | 🟡 Aunoa ya tiene GLS | 🟡 ciclo largo | 🟡 integración TMS | 🟢 (postal = servicio básico) | No primero |
| Hoteles independientes | 🟡 | 🔴 HiJiffy ancla ~€150-400/mes | 🔴 HiJiffy 2.500+ hoteles, Bookline 1.500+ | 🟢 | 🟡 | ❌ | Descartar |
| Educación/academias | 🟡 (el dolor es captación, no soporte) | 🟡 | 🟡 Varkia etc. | 🟢 | 🟢 | ❌ | No es CX, es revenue |
| Gestorías/asesorías | 🔴 80,6% <10 empleados; 79,6% no quiere cambiar ([Wolters Kluwer](https://www.wolterskluwer.com/es-es/expert-insights/radiografia-del-despacho-profesional-2025)) | 🔴 | — | — | — | ❌ | Descartar |
| Automoción | 🟡 | 🟡 solo grupos concesionarios | 🔴 Caleida 100+ concesionarios | 🟡 | 🔴 voz/BDC | ❌ | Descartar |
| Marketplaces servicios / SaaS B2B ES | No investigado en profundidad en esta pasada | — | — | — | — | — | Pendiente si interesa |

### El mapa de la competencia managed española (tu capa L4 real)

- **Aunoa** (Valencia): managed explícito ("supervisión diaria de la IA"), pero roster enterprise/AAPP: GLS, Grupo Caja Rural, Ayuntamiento de Valencia ([aunoa.ai](https://aunoa.ai/quienes-somos/)). No pelea tu segmento 50-400.
- **Inbenta** → 500+ empleados; **Botslovers** → Alcampo/Carrefour; **1MillionBot** → sector público. Enterprise todos.
- **Centribal/Chattigo** → SaaS low-end (€125/mes, $95-350/mes) apoyados en Kit Digital.
- **Voice low-end** (Nolam, OptimusCall, Telqi, Safina…) → micro-pyme vertical.
- **Conclusión verificable: el managed para 50-400 empleados en España está vacío también FUERA de e-commerce.** Tu hueco no es de vertical: es de segmento. Confianza media (argumento por ausencia).

### Señales de financiación del comprador (Kit Digital — estado verificado 2026-06-10)

- **Hoy NO hay convocatoria abierta.** Las últimas (Segmento III y comunidades de bienes) cerraron el 31-oct-2025 ([Red.es](https://www.red.es/es/actualidad/noticias/kit-digital-cierra-las-dos-ultimas-convocatorias-que-quedaban-abiertas-tras-mas)); la de medianas (Segmentos IV-V, bonos €25-29K) cerró el 30-jun-2025.
- **Pero el programa NO está muerto:** la Orden TDF/39/2026 (BOE 28-ene-2026) reactiva los fondos remanentes, elimina la fecha de fin ("hasta agotamiento de fondos") e incorpora por primera vez categorías de IA (chatbots/asistentes virtuales); en marzo 2026 el Gobierno anunció €40M para IA en empresas <50 empleados ([digital.gob.es](https://digital.gob.es/comunicacion/notas-prensa/secretaria-digitalizacion-e-inteligencia-artificial/2026/03/el-gobierno-invertira-40-millones-de-euros-para-facilitar-el-acc)). Las nuevas convocatorias deben abrirse y resolverse antes de **agosto 2026** (límite de ejecución NextGenerationEU) y a fecha de este informe Red.es aún no las ha publicado ([kitdigital.red.es/convocatorias](https://kitdigital.red.es/convocatorias)).
- **Cómo aprovecharlo:** (a) como agente digitalizador la adhesión histórica exigía facturación previa acreditada en soluciones similares (~€100K en 2 años) — con €0 facturados Auyan probablemente no califica aún; la vía realista es partnership con un digitalizador ya adherido (catálogo de +10.700) que canalice el bono, o revisar si las nuevas bases bajan umbrales; (b) los clientes solicitan el bono cuando abra la convocatoria y lo gastan con digitalizadores adheridos.
- **Veredicto: palanca oportunista, NO pilar de GTM.** Ventana incierta y corta (si abre, vuela por orden de llegada antes de agosto). Vigilar [kitdigital.red.es/convocatorias](https://kitdigital.red.es/convocatorias) y decidir partnership si abre. El driver comercial robusto sigue siendo la Ley 10/2025.

Dato pro-managed adicional: solo 21,1% de empresas 10+ empleados usa IA (INE/ONTSI 2025; micro: 13,4%; uso productivo real en pymes según IndesIA: 2,9%) y las barreras citadas son conocimiento técnico y talento interno ([ONTSI](https://www.ontsi.es/es/digitalizacion-empresas-espanolas-2025), [IndesIA](https://www.indesia.org/wp-content/uploads/2025/05/INDESIA_BAROMETRO-IA-PYMES-2025.pdf)). La pyme española no quiere configurar — quiere el resultado. Tu tesis de entrega es correcta; tu duda es de vertical, no de modelo.

---

## 5. Recomendación accionable

### Decisión recomendada: bifurcar el discovery, no pivotar

**Semanas 1-2 (coste €0):** ejecuta el sprint de `customer-discovery.md` tal cual está diseñado (Mom Test, pregunta de oro, cohortes), pero con 2 cohortes de 5:

1. **Cohorte A — e-commerce escenario 4** (ya usan Gorgias AI/Permut/GuruSup/Tidio): valida si perciben el coste de operar el bot ellos mismos. Pregunta de oro intacta: "¿lo siguen usando o lo apagaron? ¿por qué?".
2. **Cohorte B — comercializadoras de energía independientes (10-100 empleados):** valida el dolor Ley 10/2025. Preguntas de comportamiento pasado: "¿qué habéis hecho ya para adaptaros a la ley de atención a la clientela? ¿quién lleva hoy las reclamaciones y en qué plazos respondéis? ¿cuánta gente tenéis en atención?". Tu credencial de entrada es la misma (6 años DIGI = sector regulado con SAC supervisado, portabilidades, facturación, bajas — más transferible a energía que a moda).

**Criterio de decisión (mes 1):** si ≥2 de 5 en una cohorte muestran dolor + presupuesto + dueño de decisión → ese es el vertical del Founding Partner 1. Si ambas validan, e-commerce gana por fit de stack (Shopify ya construido) y energía queda como expansión con fecha (la ley aprieta en Q4 2026, justo cuando tendrías 1-2 casos de estudio).

### Por qué NO pivotar hoy a energía directamente

Sé honesto con los contras: (a) el canal dominante de energía es telefónico y tú no tienes voz hasta mes 12+ — tu wedge ahí es el back-office de reclamaciones escritas/email con SLA auditable, no el call center; (b) no hay un "Shopify de comercializadoras": la integración con sus sistemas de facturación/ATR es heterogénea — empezarías con menos skills L2/L3 que en e-commerce; (c) la exención <5% del call center 24h debilita parte del argumento (queda por verificar el texto final); (d) cero validación tuya también en ese vertical. Pivotar de un vertical no validado a otro no validado es cambiar de ansiedad, no de información.

### Top 3 final

| # | Vertical | Por qué | Condición |
|---|---|---|---|
| 1 | **E-commerce ES, escenario 4, tier Growth+** | Stack 90% listo, hueco managed verificado, Crescendo no está en España, anclaje de precio solo daña el Starter | Validar con cohorte A; vender Growth como entrada, no Starter |
| 2 | **Comercializadoras de energía independientes** | Dolor nº1 documentado de España (968K reclamantes), deadline legal 28-dic-2026, cero IA desplegada, queja pública de ACIE por costes, tu background regulado aplica | Validar con cohorte B; wedge = compliance de reclamaciones escritas, no teléfono |
| 3 | **Gestoras de apartamentos turísticos 50-500 unidades** | Texto/WhatsApp-first (tu stack), 24/7 multiidioma, sector consolidándose hacia tu ICP por el registro NRUA, sin incumbent de CX-IA | Activar solo si A y B fallan, o como vertical 2 en mes 12+; requiere adapter PMS + multiidioma |

### Lo que NO hacer

- No tocar clínicas, fincas, talleres, gestorías, hoteles sueltos: o están comoditizados a €49-250/mes, o exigen voz, o el ASP no llega.
- No construir NADA nuevo (ni voz, ni adapters de energía) antes de las 10 conversaciones. El stack actual sobra para demostrar valor en ambas cohortes.
- No usar "Mundimoto 43% con Permut" en pitches hasta verificar la fuente.
- No tratar la Ley 10/2025 como pitch de miedo sin verificar el texto consolidado (exenciones de la enmienda) con el BOE en mano.

---

## 6. Pendientes de verificación (antes de decisiones irreversibles)

1. Texto literal del art. 2 de la Ley 10/2025 (umbrales "o" vs "y"; alcance exacto de la exención <5% para energía/telco) — [BOE-A-2025-26698](https://www.boe.es/buscar/act.php?id=BOE-A-2025-26698).
2. Orden TDF/39/2026 (Kit Digital IA): bases, importes y requisitos de agente digitalizador.
3. Cliente Mundimoto↔Permut (no hay fuente pública que lo confirme).
4. Nº de comercializadoras con 10-100 empleados (cruzar [censo CNMC](https://sede.cnmc.gob.es/listado/censo/2) con eInforma/SABI — 2-3 horas de trabajo manual, y de paso sale la lista de outreach de la cohorte B).
5. Resolution rates reales de competidores: no existe auditoría independiente; todos los % son auto-reportados.

> Limitación metodológica: parte de las fuentes primarias (BOE, PDFs oficiales, pricing pages) devolvieron 403 desde el entorno de investigación; esos claims están marcados con confianza media y citan análisis secundarios consistentes entre sí.
