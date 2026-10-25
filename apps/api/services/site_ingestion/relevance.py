from __future__ import annotations

import re

from apps.api.services.site_ingestion.models import Priority

_NOISE = re.compile(r"privac|cookie|ccpa|pipeda|appi|gdpr|rgpd|lopd", re.IGNORECASE)
_LOW_PRIORITY = re.compile(r"terms|condicion|legal|aviso|subscription-policy", re.IGNORECASE)
_CX_TOPICS = re.compile(
    r"faq|pregunta|ayuda|help|envio|envío|shipping|devoluc|return|cambio|exchange|garant|"
    r"warrant|contact|about|sobre|nosotros|quienes|talla|size|cuidado|care|pago|payment|"
    r"tienda|store|politica|policy|condicion|terms|legal|seguimiento|track|club|fidel|loyal|"
    r"regalo|gift|reembolso|refund",
    re.IGNORECASE,
)
_FOREIGN_LOCALE_PREFIX = re.compile(r"^/(en|fr|de|it|pt|nl|ca|eu)(-[a-z]{2})?(/|$)", re.IGNORECASE)


def is_foreign_locale(path: str) -> bool:
    return bool(_FOREIGN_LOCALE_PREFIX.search(path))


def is_noise(handle_or_path: str) -> bool:
    return bool(_NOISE.search(handle_or_path))


def priority_of(handle_or_path: str) -> Priority:
    return Priority.LOW if _LOW_PRIORITY.search(handle_or_path) else Priority.NORMAL


def is_cx_topic(text: str) -> bool:
    return bool(_CX_TOPICS.search(text))


def crawl_rank(path: str) -> int:
    if path in ("", "/"):
        return 20
    if is_foreign_locale(path) or is_noise(path):
        return -1
    score = 0
    if is_cx_topic(path):
        score += 10
    if "/pages/" in path or "/policies/" in path:
        score += 3
    if "/blog" in path:
        score -= 5
    if "/products/" in path or "/collections/" in path:
        score -= 20
    return score
