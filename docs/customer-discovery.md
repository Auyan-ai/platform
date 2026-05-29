# Auyan — Customer Discovery Sprint

Fuente estratégica: `docs/auyan-master-context.md` (ICP, competencia, GTM) y `docs/billing-manual.md` (tamaño de cliente, tiers). Este doc es el output de un diagnóstico tipo YC office-hours (sesión 53) y es el plan operativo para **validar demanda antes de construir más**.

> **Regla dura de este sprint:** no tocar el agente hasta haber mandado 3 mensajes de descubrimiento. Outreach y producto pueden correr en paralelo, pero el outreach manda.

---

## 1. Por qué existe este doc (el reencuadre)

Hechos sobre la mesa: ~75k líneas de código, ~90% del stack construido, **0 clientes reales con los que se haya hablado**. El tenant "Lunaria" es un simulador de vuelo, no un cliente.

La ansiedad por la competencia (GuruSup, Permut, ElevenAgents, Sierra, Decagon, 14.ai) es un **síntoma**, no la causa. La causa real es que no se ha validado que el dolor existe ni que el wedge resuena. El instinto de seguir construyendo (verificar el agente, integrar Chatwoot, optimizar el simulator) es build-first avoidance: trabajo que se siente productivo pero que no responde la única pregunta que importa ahora.

La pregunta que este sprint responde: **¿las marcas Shopify españolas del ICP tienen dolor de soporte suficiente, y quieren el resultado sin cargar con la implementación/mantenimiento?**

El producto de calidad (que el bot responda bien) es *table-stakes* en 2026 — cualquiera con Claude lo logra. El diferenciador real de Auyan es la **operación gestionada**: configurar, mantener y optimizar el agente del cliente. Este sprint valida si ese diferenciador le importa a alguien que paga.

---

## 2. Objetivo y criterio de éxito

| Métrica | Meta del sprint |
|---|---|
| Marcas ICP identificadas | 10 |
| Mensajes de descubrimiento enviados | 3 (mínimo, esta semana) |
| Conversaciones agendadas | 3 |
| Respuestas de formulario (fallback) | las que caigan |

Éxito no es "me dijeron que les gusta la idea". Interés ≠ demanda. Éxito es **aprender hechos del pasado**: qué herramienta usan, cuántos tickets manejan, si probaron IA y por qué la siguen usando o la apagaron. El competidor real es el status quo (su forma actual de manejar el soporte), no Sierra.

---

## 3. A quién buscar (ICP calibrado)

Objetivo: **Starter ICP**. El extremo pequeño del ICP real, NO la SMB más chica posible (eso valida el ICP equivocado y genera falsos negativos).

| Segmento | Facturación anual | Tickets/mes | ¿Target del sprint? |
|---|---:|---:|---|
| Bajo ICP | 1–2,5 M€ | 200–600 | No (salvo dolor clarísimo) |
| **Starter ICP** | **2,5–5 M€** | **500–1.000** | **Sí — foco** |
| Growth ICP | 5–12 M€ | 1.500–3.000 | Sí, si aparece |
| Scale ICP | 12–30 M€ | 3.000–10.000 | No todavía |

**Filtro duro:** que exista **≥1 persona cuyo trabajo sea CX**. Si nadie en la empresa tiene el soporte como su trabajo, no hay dolor que Auyan resuelva.

**Verticales:** mantener el clúster retail (ropa, cosmética, suplementos) + meter **2–3 marcas de auto/moto**. El ticket más alto de auto/moto no es lo que importa (Auyan cobra por volumen + repetitividad, no por AOV); lo valioso es que esas marcas suelen tener **alto volumen de preguntas de compatibilidad/fitment pre-venta**, que es un caso de uso fuerte para IA. Regla: comprometerse a **UN solo vertical** cuando se defina el wedge; aquí estamos explorando para decidir cuál.

### Las dos cohortes (clave)

Partir las 10 marcas en dos grupos y **comparar sus respuestas** — ese contraste es el mapa del mercado:

| Cohorte | Qué son | Qué confirman |
|---|---|---|
| **Ya usan bot/IA** (Gorgias AI, Tidio, Intercom Fin, Zendesk AI, Zowie...) | Ya cruzaron el abismo de adopción. Tienen comportamiento pasado real. | Si lo apagaron → comprar ≠ funciona. Si lo mantienen pero lo configuran a mano sin tiempo → **wedge exacto de Auyan**. |
| **No usan bot** | Manejan todo manual o con WhatsApp crudo. | Su objeción de adopción ("lo evaluamos pero...") = barrera del mercado. |

Cuidado: con la cohorte "ya usa bot", **no llegar oliendo a reemplazo**. Llegar con curiosidad por SU setup. Si huele a pitch de "vengo a cambiar tu Gorgias", se cierran.

---

## 4. Cómo encontrarlos (herramientas — €0 para 10)

Para una lista de 10 no hay que pagar nada. Pagar ahorita es optimización prematura (el mismo instinto build-first).

| Herramienta | Para qué | Costo |
|---|---|---|
| **Store Leads** (storeleads.app) | Filtro **país (España) + app instalada** en una query. Ej: "Shopify en España con Gorgias instalado" = ICP + ya-usa-bot de un tiro. | Free para navegar/armar lista a mano (export masivo $250+/mes — no hace falta). |
| **Wappalyzer** | Extensión Chrome: rayos-X del stack de cualquier tienda puntual (¿Gorgias? ¿Tidio? ¿WhatsApp crudo?). Listas "Find Gorgias customers" con export. | Extensión free. |
| **view-source manual** | Ctrl-F `cdn.shopify.com` (confirma Shopify) + `gorgias`/`tidio`/`zendesk`/`intercom`/`whatsapp` (confirma soporte). | €0 |
| **Apollo.io** | Filtro technographic "usa Shopify" + email/teléfono del decisor. | $49/mo — **solo cuando haga falta contacto a volumen, todavía no.** |

Flujo sugerido: Store Leads (free) para filtrar España + Shopify + app de soporte → exportar 10 a mano → Wappalyzer/view-source para confirmar stack → LinkedIn + página de contacto para encontrar al fundador o responsable de CX.

---

## 5. El mensaje de descubrimiento

Encuadre: **aprender, no vender**. El outreach de aprendizaje convierte mucho mejor que el de venta. Los 6 años en atención al cliente en DIGI son el ticket de entrada — dan legitimidad sin necesidad de producto listo.

> Hola [Nombre], soy Kenny. Pasé 6 años en atención al cliente en DIGI antes de meterme de lleno en e-commerce. Estoy investigando cómo los equipos de CX de marcas Shopify españolas están manejando el volumen de soporte y las herramientas de IA (Gorgias AI, Permut y compañía). No te vendo nada — estoy aprendiendo del mercado antes de construir. ¿Me regalarías 20 min para que me cuentes cómo lo llevan en [Marca]? Te comparto lo que voy aprendiendo de otras marcas, que suele ser útil para comparar. Si no tienes tiempo, te dejo un formulario corto (5 min), lo que mejor te venga.

**Variante para marcas con mala reseña pública (Trustpilot 1–3★):** abrir mencionando que viste una reseña sobre tiempos de respuesta / soporte y que justo eso es lo que estás investigando. Crea relevancia inmediata sin sonar a ataque.

**Variante para cohorte "ya usa bot":** cambiar el cuerpo a curiosidad sobre su herramienta — "vi que usan [Gorgias AI / Tidio], justo estoy aprendiendo cómo les está yendo a las marcas con esas herramientas en la práctica". Eso abre directo a la pregunta de oro.

---

## 6. El formulario (fallback, no reemplazo)

El formulario baja la fricción para quien no quiere videollamada, y a futuro es un activo de contenido ("Estado del soporte en e-commerce español 2026"). **No reemplaza las conversaciones** — el oro está en la llamada.

Todas las preguntas son del pasado/hechos (Mom Test compliant), no hipótesis:

1. ¿Qué helpdesk usan hoy? (Gorgias, Zendesk, Freshdesk, Intercom, WhatsApp, email...)
2. ¿Cuántos tickets/conversaciones manejan al mes, aprox.?
3. ¿Cuántas personas se dedican al soporte?
4. ¿Han probado alguna IA/bot para soporte? ¿Cuál?
5. **(Si probaron) ¿La siguen usando o la dejaron? ¿Por qué?** ← pregunta de oro
6. ¿Quién la configura/mantiene y cuánto tiempo le dedica al mes?
7. ¿Qué % de los tickets dirías que son repetitivos?
8. ¿Cuál es la mayor frustración del soporte hoy? (abierta)
9. ¿Estarías abierto/a a 15 min de videollamada para profundizar? (email)

---

## 7. La pregunta de oro

> **"¿Lo siguen usando o lo apagaron? ¿Por qué?"**

| Respuesta | Lo que confirma |
|---|---|
| "Lo apagamos, daba respuestas malas" | Comprar el bot ≠ que funcione → hueco de operación. |
| "Lo usamos pero hay que configurarlo siempre y nadie tiene tiempo" | Quieren resultado, no mantenimiento → **wedge exacto de Auyan.** |
| "Funciona bien, contentos" | Ahí no hay dolor → tachar y seguir. |

---

## 8. Plan de ejecución (esta semana)

1. Armar lista de **10** marcas Starter ICP (Store Leads free + Wappalyzer), partidas en cohortes "ya usa bot" / "no usa bot". → verify: 10 nombres con stack confirmado.
2. Enviar **3** mensajes de descubrimiento (LinkedIn / email del fundador o CX lead). → verify: 3 enviados.
3. Conseguir **3** conversaciones agendadas (o respuestas de formulario si no hay tiempo). → verify: 3 calls en calendario.
4. **No tocar el agente hasta tener los 3 mensajes enviados.**

---

## 9. Qué NO hacer

- No pagar herramientas todavía (€0 alcanza para 10).
- No pitchear producto — encuadre de aprendizaje siempre.
- No hacer preguntas hipotéticas ("¿usarías un servicio que...?"). Solo pasado/hechos.
- No agendar demos hasta confirmar que el dolor existe. Si piden ver algo, Lunaria sirve como demo compartible en pantalla.
- No dejar que una marca demasiado pequeña (<2,5 M€ sin dolor claro) consuma el foco.

---

## 10. Hipótesis a validar (pricing / wedge / GTM)

Output del `/plan-ceo-review` acotado (sesión 53). Pricing, wedge y GTM no son tres preguntas separadas: son tres lecturas de **una sola** — *¿una marca Starter-ICP siente suficiente dolor de soporte como para pagar por convertirlo en problema de otro?* Si el dolor base no es real, las tres se caen juntas. Las llamadas validan el dolor primero; el resto se lee de la misma conversación.

Regla: cada pregunta es de **comportamiento pasado**, nunca hipótesis. Prohibido "¿pagarías X?" / "¿usarías esto?".

### Pricing

| Supuesto | Riesgo si falla | Pregunta de discovery |
|---|---|---|
| Starter-ICP paga ~€890/mes por CX gestionado con IA | Tier mal anclado: nadie a ese tamaño paga recurrente, o pagan mucho menos | "¿Cuánto pagan hoy al mes en herramientas de soporte + add-ons de IA? ¿Y cuánto cuesta la persona/equipo de CX?" |
| Cobrar por tickets incluidos es la métrica que les hace sentido | Si el dolor escala con headcount/horas, el overage genera fricción | "¿Cómo piensan el coste del soporte: por persona, por ticket, por horas? ¿Qué les dolió más en el bolsillo cuando subió el volumen?" |
| Hay presupuesto y un dueño de la decisión | Sin dueño de presupuesto el ciclo se eterniza | "La última herramienta/proveedor de soporte que contrataron, ¿quién decidió y de qué presupuesto salió?" |

### Wedge (el crítico)

| Supuesto | Riesgo si falla | Pregunta de discovery |
|---|---|---|
| Quieren el resultado sin configurar/mantener la IA → pagan "gestionado", no self-serve | El riesgo NO es precio: Gorgias Pro $360/mes + IA $0,90–1/resolución sale parecido a tu €890, y más caro sumando horas de su gente. El riesgo real es que NO perciban ese coste humano porque la nómina ya está pagada | (ya usa bot) "¿Quién lo configura y mantiene? ¿Cuánto tiempo/mes le mete? ¿Lo siguen usando o lo apagaron, por qué?" |
| Valoran que el agente HAGA acciones, no solo responda FAQs | Si 80% es FAQ repetitiva, las skills L2/L3 son sobre-ingeniería para el wedge inicial | "De los tickets repetitivos, ¿qué % son solo preguntas vs cosas que piden una acción (reembolso, cambio de pedido)?" |
| El valor es absorber crecimiento de volumen sin crecer headcount (evitar el 3er/4º agente), no botar a los que ya tienen | Si no planean crecer o el coste del próximo agente no les duele, el ROI de evitar-contratación no aplica. Reemplazar al equipo entero es BPO, no Auyan | "¿Cómo creció tu equipo de soporte conforme subió el volumen? En picos, ¿contratas, metes horas extra o se acumula? ¿Cuánto cuesta y tarda meter un agente nuevo?" |

Nota: Sierra y Decagon también mantienen al equipo humano para escalados (son augmentation, no reemplazo). El diferenciador de Auyan vs ellos NO es "conservas tu equipo" — es segmento (e-commerce español pequeño que ellos no priorizan), precio y profundidad de vertical.

### GTM

| Supuesto | Riesgo si falla | Pregunta / señal |
|---|---|---|
| Outreach directo + comunidades + contenido me lleva a ellos | Si no responden a un desconocido, el motor no arranca; hay que ir por referidos/partners | Response rate de los 3 mensajes ES la validación. + "¿Cómo eligieron las últimas herramientas: recomendación, búsqueda, partner, agencia?" |
| Shopify ES genérico es el vertical para arrancar | El dolor puede ser más agudo en un sub-vertical; genérico diluye el mensaje | A lo largo de las 10 calls: ¿qué sub-vertical tiene el dolor más agudo? Deja que el dato elija el vertical |
| DIGI + "aprendiendo no vendiendo" consigue la reunión | <30% respuesta = mensaje o canal roto, revisar antes de escalar | Response rate del mensaje de descubrimiento |
