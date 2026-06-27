# ADR 0002 — Modelo de negocio: Managed AI Service

**Estado:** Aceptada
**Fecha:** 2026-05-22 (pivot estratégico)

> Este es un ADR de **producto**, no de software. Está aquí porque condiciona
> toda la arquitectura técnica: qué se construye, para quién y qué nunca se
> construye.

## Contexto

Auyan resuelve el soporte al cliente (CX) de e-commerce español con IA. La
pregunta fundacional no era "¿qué tecnología usamos?" sino "¿qué vendemos?".
El mercado del CX está en su tercera ola: de servicios → SaaS → **servicio
AI-native** (el cliente paga por tener el problema resuelto, no por una
herramienta). El equipo fundador son 2 personas con experiencia profunda en CX
(6 años en una telco española) pero capital limitado (20-50K€).

## Decisión

**Auyan es un Managed AI Service: configuramos, mantenemos y optimizamos el
agente de IA del cliente. El cliente conserva su propio equipo de soporte humano
para los escalados. Somos su equipo externo de Agent Engineers.**

Concretamente:
- **No** somos un BPO: no hay agentes humanos de Auyan atendiendo tickets.
- **No** somos un SaaS self-serve: el cliente no configura nada, no gestiona
  prompts ni créditos.
- El entregable diferenciador es un **reporte semanal proactivo** con propuestas
  concretas de mejora que el cliente aprueba o rechaza.

Esto se traduce en arquitectura: un **control plane interno potente** (editor de
AOPs, simulator, approvals, QA, audit) + una **experiencia cliente deliberadamente
simple** (dashboard read-only + reportes). La complejidad vive de nuestro lado.

## Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| **BPO con agentes humanos** | Margen 30-40%, no escala sin contratar, bottleneck operacional. El equipo no quiere atender tickets 8h/día. |
| **SaaS self-serve** (estilo Permut, GuruSup, Chatbase) | Race to the bottom en precio. La ventaja injusta del equipo (expertise en CX) vale cero si el cliente se autoconfigura. |
| **Implementador puro** encima de plataformas existentes | Captura poco valor, fácil de saltar por el cliente, defensibilidad baja. |
| **Enterprise tipo Sierra** | Requiere clientes de $200K+/año y 400+ empleados. Fuera del alcance de un equipo de 2. |

## Consecuencias

**Positivas:**
- Margen de contribución ~79% desde el primer cliente.
- La defensibilidad es operativa (el flywheel de conocimiento: cada escalado que
  el cliente resuelve entrena al agente vía el slow agent), no solo tecnológica.
- Justifica construir el control plane interno como producto de primera clase —
  que es donde está el trabajo de ingeniería interesante.

**Negativas / costos asumidos:**
- No escala infinitamente sin gente: cada cliente consume ~2-2.5h/semana de
  operación experta. El modelo apunta a decenas de clientes, no a miles.
- Obliga a construir DOS superficies (control plane interno + dashboard cliente),
  más trabajo que un solo SaaS.
- La promesa "mejora cada semana" crea una obligación operativa recurrente.
