# ADR 0011 — Transcripción de notas de voz de WhatsApp detrás de `Transcriber`

**Estado:** Propuesta (pasa a Aceptada cuando el mini-benchmark de C0.5 elija el proveedor
y se confirme su DPA/residencia UE)
**Fecha:** 2026-10-01 (implementación del Sprint 2, PR-7)

## Contexto

En WhatsApp muchos compradores mandan **notas de voz**. Decisión cerrada en la s79: se
transcriben ya, con el proveedor elegido por un mini-benchmark (C0.5). Condiciones:

- **Literal o nada.** Un número de pedido o un email reescrito es un error de integración,
  no de estilo: el agente buscaría otro pedido. Es criterio eliminatorio.
- Voz = PII. El proveedor es un subprocesador: DPA, residencia UE y retención cuentan.
- Regla dura del Sprint 2 (determinismo): lo que no se puede razonar (audio ilegible,
  demasiado largo, sin proveedor) recibe un **mensaje fijo del tenant**, sin grafo.
- Meta borra la media entrante: hay que descargarla al procesar el turno.

## Decisión

1. **Interfaz `Transcriber`** (`apps/api/integrations/transcription/`):
   `transcribe(audio, mime_type, language="es") -> Transcript(text, duration_s, provider,
   model, cost_usd)`. `get_transcriber(settings)` devuelve el configurado o **None**.
2. **Apagado por defecto** (`TRANSCRIPTION_PROVIDER` vacío): sin proveedor, el comprador
   recibe el mensaje fijo "no hemos podido escuchar tu nota de voz, ¿nos la escribes?".
3. **Adapter provisional: OpenAI** (`gpt-4o-transcribe`, prompt de transcripción literal).
   OpenAI ya es subprocesador de Auyan (embeddings). Solo se activa en staging para el E2E
   mientras no haya resultado del benchmark.
4. **Duración máxima 5 min** (`TRANSCRIPTION_MAX_SECONDS`), medida en código desde el OGG
   (granule position / 48 kHz). Más larga → mensaje fijo, sin llamar al proveedor.
5. **Coste** estimado por minuto (`TRANSCRIPTION_COST_PER_MINUTE_USD`) y sumado al uso del
   tenant. **LangSmith**: run `transcribe_audio` con proveedor, modelo, duración, latencia y
   coste, correlacionado por `tenant_id`/`conversation_id`/`message_id`; **nunca** el audio
   ni el texto (el texto entra como contenido del turno con las reglas de PII).
6. **Benchmark** reproducible: `apps/api/scripts/benchmark_stt.py` sobre ~30 notas reales en
   `apps/api/stt_bench/` (en `.gitignore`): WER, acierto exacto de números de pedido y
   emails, latencia p50/p95 y coste. Candidatos: ElevenLabs Scribe v2, OpenAI
   gpt-4o-transcribe, Google Chirp (UE), Mistral Voxtral o Gladia (UE) y Wispr Flow (si da
   transcripción literal). Cada candidato entra como adapter detrás de `Transcriber`.

## Consecuencias

- Cambiar de proveedor es un adapter nuevo + una variable de entorno; el worker no cambia.
- Hasta cerrar C0.5, en producción las notas de voz reciben el mensaje fijo (sin coste ni
  subprocesador nuevo).
- Pendiente al aceptar: nombre del proveedor ganador, resultados del benchmark (tabla), DPA
  y región, y retirar el adapter provisional si pierde.
