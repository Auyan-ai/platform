# docs/archive — Documentos históricos

> ⚠️ **Nada en esta carpeta es fuente de verdad.** Son diseños ya implementados o material
> superado, conservados solo como registro del racional. Para el estado vigente:
> `docs/progress.md`. Para la verdad técnica: el código + tests. Ni humanos ni agentes deben
> tomar instrucciones de estos archivos.

**Regla de archivado** (convención en `CLAUDE.md`): cuando un documento de diseño se implementa
y verifica, se mueve aquí con el banner de histórico. La sección compactada de `progress.md`
va a `docs/progress-archive.md`, no aquí.

| Archivo | Qué era | Verdad vigente |
|---|---|---|
| `simulator-design.md` | Diseño del Simulator MVP (Sub-PR 0.10) | `apps/api/simulator/` + `routers/simulations.py` |
| `aop-canonical-design.md` | Diseño de los 8 AOPs canónicos e-commerce ES + fixes de grafo (s59) | `apps/api/aops/canonical.py` + `agents/nodes/select_aop.py` |
