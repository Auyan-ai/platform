"""Clave canónica de una fuente de la KB (ADR 0015 §3).

Dos URLs que apuntan a la misma página dan la misma clave. La función SQL
`kb_canonical_source_key` de la migración 20261025000001 hace lo mismo; los dos
lados se comparan en `tests/test_kb_lifecycle_pg.py`.
"""

from __future__ import annotations

import hashlib
import re

_SCHEME = re.compile(r"^https?://", re.IGNORECASE)


def canonical_source_key(url: str) -> str:
    """Minúsculas en el host, sin esquema, sin `www.`, sin query, sin fragmento, sin `/` final.

    Lanza `ValueError` si la URL no tiene host.
    """
    rest = _SCHEME.sub("", url.strip())
    rest = rest.split("#", 1)[0].split("?", 1)[0]
    host, slash, path = rest.partition("/")
    host = host.lower().removeprefix("www.")
    key = (host + slash + path).rstrip("/")
    if not host:
        raise ValueError(f"URL sin host: {url!r}")
    return key


def content_sha256(content: str) -> str:
    return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()
