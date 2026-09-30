"""Mini-benchmark de voz a texto (Sprint 2 · C0.5) → ADR 0011.

Corpus (NO se commitea: voz real = PII) en `apps/api/stt_bench/`:
    nota01.ogg + nota01.txt   (transcripción de referencia hecha a mano, literal)
    nota02.ogg + nota02.txt
    …

Uso (desde apps/api, con la key del proveedor en el entorno):
    python -m scripts.benchmark_stt --provider openai --model gpt-4o-transcribe
    python -m scripts.benchmark_stt --provider openai --model whisper-1 --json out.json

Métricas por proveedor: WER (distancia de edición por palabras, normalizada), acierto
EXACTO de números de pedido y emails de la referencia (criterio eliminatorio: literal),
latencia p50/p95 y coste estimado. Para comparar otro proveedor (ElevenLabs Scribe v2,
Google Chirp UE, Voxtral, Gladia, Wispr Flow) se añade su adapter detrás de
`integrations/transcription.Transcriber` y se registra en `get_transcriber`.
"""

# ruff: noqa: E402,I001

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from apps.api.integrations.transcription import get_transcriber

CORPUS_DIR = Path(__file__).resolve().parents[1] / "stt_bench"
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_ORDER_RE = re.compile(r"#?\b\d{3,6}\b")


def normalize_words(text: str) -> list[str]:
    """Minúsculas, sin tildes ni puntuación: WER sobre palabras, no sobre formato."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^\w@.#+-]+", " ", text)
    return [w.strip(".") for w in text.split() if w.strip(".")]


def word_error_rate(reference: str, hypothesis: str) -> float:
    ref, hyp = normalize_words(reference), normalize_words(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1] / len(ref)


def critical_tokens(text: str) -> set[str]:
    """Números de pedido y emails: lo que NUNCA puede reescribirse."""
    emails = {e.lower() for e in _EMAIL_RE.findall(text)}
    orders = {o.lstrip("#") for o in _ORDER_RE.findall(_EMAIL_RE.sub(" ", text))}
    return emails | orders


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1))))
    return ordered[k]


@dataclass
class SampleResult:
    name: str
    wer: float
    critical_expected: int
    critical_hit: int
    latency_ms: int
    duration_s: float | None
    cost_usd: float
    error: str | None = None


async def run_benchmark(provider: str, model: str, corpus: Path) -> list[SampleResult]:
    settings = SimpleNamespace(
        transcription_provider=provider,
        transcription_model=model,
        transcription_cost_per_minute_usd=0.006,
        openai_api_key=SimpleNamespace(
            get_secret_value=lambda: __import__("os").environ["OPENAI_API_KEY"]
        ),
    )
    transcriber = get_transcriber(settings)  # type: ignore[arg-type]
    if transcriber is None:
        raise SystemExit("Proveedor vacío")
    results: list[SampleResult] = []
    for audio_path in sorted(corpus.glob("*.ogg")):
        ref_path = audio_path.with_suffix(".txt")
        if not ref_path.exists():
            print(f"(sin referencia) {audio_path.name}")
            continue
        reference = ref_path.read_text(encoding="utf-8").strip()
        expected = critical_tokens(reference)
        started = time.monotonic()
        try:
            transcript = await transcriber.transcribe(audio_path.read_bytes(), "audio/ogg")
        except Exception as exc:
            results.append(
                SampleResult(audio_path.stem, 1.0, len(expected), 0, 0, None, 0.0, str(exc))
            )
            continue
        latency = int((time.monotonic() - started) * 1000)
        hit = len(expected & critical_tokens(transcript.text))
        results.append(
            SampleResult(
                name=audio_path.stem,
                wer=round(word_error_rate(reference, transcript.text), 4),
                critical_expected=len(expected),
                critical_hit=hit,
                latency_ms=latency,
                duration_s=transcript.duration_s,
                cost_usd=transcript.cost_usd,
            )
        )
    return results


def summarize(results: list[SampleResult]) -> dict[str, float]:
    ok = [r for r in results if r.error is None]
    latencies = [float(r.latency_ms) for r in ok]
    expected = sum(r.critical_expected for r in results)
    return {
        "samples": len(results),
        "errors": len(results) - len(ok),
        "wer_mean": round(statistics.mean(r.wer for r in results), 4) if results else 0.0,
        "critical_accuracy": round(sum(r.critical_hit for r in results) / expected, 4)
        if expected
        else 1.0,
        "latency_p50_ms": percentile(latencies, 50),
        "latency_p95_ms": percentile(latencies, 95),
        "cost_usd_total": round(sum(r.cost_usd for r in results), 4),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Mini-benchmark de voz a texto (C0.5)")
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--corpus", default=str(CORPUS_DIR))
    parser.add_argument("--json", default=None, help="Guarda el detalle en este archivo")
    args = parser.parse_args(argv)
    results = asyncio.run(run_benchmark(args.provider, args.model, Path(args.corpus)))
    summary = summarize(results)
    print(json.dumps({"provider": args.provider, "model": args.model, **summary}, indent=2))
    if args.json:
        Path(args.json).write_text(
            json.dumps({"summary": summary, "samples": [asdict(r) for r in results]}, indent=2)
        )


if __name__ == "__main__":
    main()
