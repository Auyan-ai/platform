from __future__ import annotations

import re
from collections import Counter

# Con menos páginas HTML en la ingesta no hay forma fiable de distinguir plantilla de contenido.
MIN_PAGES = 3

_MARKUP = re.compile(r"^[\s#>*\-+|]+|[\s|*_]+$")
_SPACES = re.compile(r"\s+")
_BLANKS = re.compile(r"\n{3,}")


def _normalize(line: str) -> str:
    """Forma comparable de una línea: sin marcas de markdown, en minúsculas y con espacios
    colapsados. Vacía si no tiene letras ni dígitos."""
    text = _SPACES.sub(" ", _MARKUP.sub("", line)).strip().lower()
    return text if any(c.isalnum() for c in text) else ""


def strip_boilerplate(markdowns: list[str]) -> list[str]:
    """Quita de cada página las líneas que aparecen en más de la mitad de las páginas.

    El HTML de una misma tienda repite bloques (bolsa de regalo, aviso de contraseña, banners)
    que trafilatura no distingue del contenido. Una línea cuenta una vez por página. Con menos
    de `MIN_PAGES` páginas se devuelve el texto tal cual. La salida conserva el orden de la
    entrada.
    """
    if len(markdowns) < MIN_PAGES:
        return list(markdowns)
    counts: Counter[str] = Counter()
    for md in markdowns:
        counts.update({n for n in map(_normalize, md.splitlines()) if n})
    repeated = {line for line, n in counts.items() if n * 2 > len(markdowns)}
    if not repeated:
        return list(markdowns)
    return [
        _BLANKS.sub(
            "\n\n",
            "\n".join(ln for ln in md.splitlines() if _normalize(ln) not in repeated),
        ).strip()
        for md in markdowns
    ]
