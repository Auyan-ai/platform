"""Extrae los números de issue que un cuerpo de PR cierra (Closes/Fixes/Resolves #N).

Uso: PR_BODY="..." python .github/scripts/closing_refs.py  -> un número por línea.
"""

import os
import re

CLOSING_RE = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+#(\d+)\b",
    re.IGNORECASE,
)


def closing_refs(body: str | None) -> list[int]:
    """Números de issue únicos, en orden de aparición. `Refs #N` no cuenta."""
    seen: dict[int, None] = {}
    for match in CLOSING_RE.finditer(body or ""):
        seen.setdefault(int(match.group(1)), None)
    return list(seen)


if __name__ == "__main__":
    for number in closing_refs(os.environ.get("PR_BODY", "")):
        print(number)
