# GTM intensivo — Julio 2026

_Objetivo: **1 cliente (piloto Founding Partner firmado y pagando, o con compromiso de pago post-piloto) al 2026-08-02.**_
_Insumos: [`discovery-targets.md`](discovery-targets.md) (10 marcas verificadas), [`customer-discovery.md`](customer-discovery.md) (mensaje + formulario + Mom Test), [`billing-resolution-prd.md`](billing-resolution-prd.md) (pricing por resolución, COGS €0,071), [`billing-manual.md`](billing-manual.md) (Founding Partner)._

## La matemática del embudo (por qué 10 targets no bastan)

| Etapa | Tasa esperada | Acumulado |
|---|---|---|
| Mensajes personalizados enviados | — | **30** |
| Respuestas | ~30% | ~10 |
| Llamadas discovery | ~60% de respuestas | ~6 |
| Dolor real + urgente detectado | ~40% de llamadas | 2-3 |
| Piloto firmado | 1 de esos | **1** |

Regla derivada: **~8 mensajes/semana, cada uno investigado y personalizado** (no spray-and-pray: el mensaje de aprendizaje solo funciona si es evidente que miraste su tienda). La lista debe crecer de 10 → ~35 targets (el barrido por view-source escala: ya está el script).

## Las dos llamadas son cosas distintas (regla dura)

1. **Llamada 1 — Discovery (Mom Test):** solo aprender. Hechos del pasado, pregunta de oro ("¿lo siguen usando o lo apagaron? ¿por qué?"). CERO pitch. Si no hay dolor → agradecer, pedir referido, tachar.
2. **Llamada 2 — Oferta (solo si hubo dolor):** se agenda al final de la 1 con permiso: "lo que me cuentas es justo lo que estoy construyendo — ¿te enseño cómo lo resolvería con vuestros tickets reales?"

Mezclarlas mata ambas: el pitch contamina el aprendizaje y el aprendizaje diluye el cierre.

## La oferta Founding Partner (definir ANTES de la primera llamada 2)

- **Setup gestionado gratis** (nosotros configuramos: KB desde sus docs/Shopify, AOPs, integración con SU helpdesk — Chatwoot/Gorgias ya en vivo; Zendesk se activa si lo piden, código listo).
- **Piloto 30 días** sobre tickets reales, con su equipo aprobando las acciones sensibles (el gate L3 con approval ES la demo de confianza).
- **Precio por resolución con suelo** (ancla COGS €0,071/resolución medido; números finales del PRD §tiers, marcados PROVISIONALES — fijar antes de la primera oferta).
- **Sin permanencia + rollback**: si a los 30 días no ves valor en tu dashboard, se apaga y no pagas más.
- Contraprestación founding: feedback semanal + case study con su nombre al cerrar el piloto.
- **Qué NO vender:** "automático", "reemplaza a tu equipo", precio contra self-serve. Vender: "tu agente IA operado por nosotros, tu equipo solo ve lo que escala".

## Plan por semanas

### Semana 1 (2-8 jul) — infra ligera + primera ola
- [ ] Formulario Tally (9 preguntas §6) — 10 min, manual
- [ ] Calendly (o Cal.com) con hueco "20 min - investigación CX" — el mensaje debe poder cerrar llamada sin ping-pong
- [ ] Perfil LinkedIn de Kenny alineado (headline: investigando CX en e-commerce ES; 6 años DIGI visibles)
- [ ] **Enviar mensajes #1-#8**: Zapato Feroz, Sepiia, Velites, Laconicum, Picsil, The Brubaker, Iguanasell, Laagam
- [ ] Ampliar lista 10 → 35 con el script de view-source (`check_stack.sh`) + Store Leads
- Métrica de cierre de semana: 8 enviados, lista a 35

### Semana 2 (9-15 jul) — segunda ola + primeras llamadas
- [ ] Follow-up suave a los sin respuesta de S1 (1 solo follow-up, a los 4-5 días, aportando algo: un dato del research, no "¿viste mi mensaje?")
- [ ] Enviar mensajes #9-#18
- [ ] Correr las llamadas discovery que caigan (meta: ≥3)
- [ ] Después de cada llamada: registrar en `discovery-targets.md` (tabla outreach) qué herramienta, tickets/mes, quién mantiene el bot, la pregunta de oro
- Métrica: 18 enviados acumulados, ≥3 llamadas hechas

### Semana 3 (16-22 jul) — tercera ola + primeras ofertas
- [ ] Enviar mensajes #19-#30
- [ ] Llamada 2 (oferta) con los 1-3 que mostraron dolor
- [ ] Demo con SUS datos si es posible: importar sus FAQs públicas a un tenant de demo y enseñar el agente respondiendo SUS preguntas reales (el onboarding Fase 1 + seed ya lo permiten en horas)
- Métrica: 30 enviados, ≥1 oferta hecha

### Semana 4 (23-31 jul) — cierre
- [ ] Negociar y firmar 1 piloto (founding partner, precios del PRD)
- [ ] Arrancar onboarding del piloto (provisioning + KB + helpdesk del cliente)
- [ ] Retro del mes: contraste cohorte A vs B (el mapa de mercado que pedía el plan original)
- Métrica: **1 piloto firmado** (éxito) o 2-3 negociaciones vivas (aceptable — el ciclo B2B puede pisar agosto)

## Reglas del mes

1. **El outreach manda sobre el código.** Solo se toca el agente si un prospect lo pide para SU piloto (ej. Zendesk E2E se activa cuando alguien con Zendesk diga sí). Todo lo demás (latencia, billing-Stripe, backlog) espera.
2. **Cadencia diaria:** 1-2 mensajes personalizados/día laborable > 8 el lunes. Investigar 15 min por marca antes de escribir.
3. **Cada viernes:** actualizar tabla de outreach + métricas de embudo en este doc. Si la tasa de respuesta < 20% tras 15 mensajes, cambiar el mensaje, no insistir.
4. **Registro fanático:** cada dato de llamada vale más que el cierre — aunque no salga cliente, el mes produce el mapa de mercado real.

## Métricas (actualizar semanal)

| Semana | Enviados | Respuestas | Llamadas | Dolor confirmado | Ofertas | Pilotos |
|---|---|---|---|---|---|---|
| S1 | | | | | | |
| S2 | | | | | | |
| S3 | | | | | | |
| S4 | | | | | | |
