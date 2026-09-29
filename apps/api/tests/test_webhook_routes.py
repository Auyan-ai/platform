"""Guard de regresión: ningún stub puede tapar a los webhooks reales por canal.

Bug: `routers/webhooks.py` declaraba un stub `POST /webhooks/zendesk` y, como ese
router se registra antes que `webhooks_zendesk`, FastAPI lo elegía siempre →
todo webhook de Zendesk devolvía `{"received": true}` sin procesar nada.
"""

from __future__ import annotations

from apps.api.routers.webhooks import router as generic_router
from apps.api.routers.webhooks_chatwoot import router as chatwoot_router
from apps.api.routers.webhooks_gorgias import router as gorgias_router
from apps.api.routers.webhooks_zendesk import router as zendesk_router
from fastapi import FastAPI
from fastapi.routing import APIRoute


def _routes(*routers: object) -> list[APIRoute]:
    app = FastAPI()
    for r in routers:
        app.include_router(r)  # type: ignore[arg-type]
    return [r for r in app.routes if isinstance(r, APIRoute)]


def test_no_duplicate_method_path_across_webhook_routers() -> None:
    seen: dict[tuple[str, str], str] = {}
    for route in _routes(generic_router, chatwoot_router, zendesk_router, gorgias_router):
        for method in route.methods:
            key = (method, route.path)
            assert key not in seen, (
                f"{method} {route.path} declarado en {seen[key]} y "
                f"{route.endpoint.__module__}: el primero tapa al segundo"
            )
            seen[key] = route.endpoint.__module__


def test_zendesk_path_resolves_to_real_handler() -> None:
    # Mismo orden que main.py: el router genérico va primero.
    matches = [
        r.endpoint.__module__
        for r in _routes(generic_router, zendesk_router)
        if r.path == "/webhooks/zendesk" and "POST" in r.methods
    ]
    assert matches == ["apps.api.routers.webhooks_zendesk"]
