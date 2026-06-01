"""Tests para core.errors: las excepciones de dominio y su handler global."""

from __future__ import annotations

import pytest
from apps.api.core.errors import (
    ConflictError,
    DomainError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationFailed,
    register_exception_handlers,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient


class TestDomainErrorClasses:
    """Cada subclase fija su `code` y `status_code` por defecto."""

    @pytest.mark.parametrize(
        ("cls", "expected_code", "expected_status"),
        [
            (UnauthorizedError, "unauthorized", 401),
            (ForbiddenError, "forbidden", 403),
            (NotFoundError, "not_found", 404),
            (ConflictError, "conflict", 409),
            (ValidationFailed, "validation_failed", 422),
        ],
    )
    def test_defaults(
        self,
        cls: type[DomainError],
        expected_code: str,
        expected_status: int,
    ) -> None:
        err = cls("algo pasó")
        assert err.code == expected_code
        assert err.status_code == expected_status
        assert err.detail == "algo pasó"

    def test_custom_code_override(self) -> None:
        err = NotFoundError("conversation gone", code="conversation_not_found")
        assert err.code == "conversation_not_found"
        assert err.status_code == 404


class TestExceptionHandler:
    """El handler global captura DomainError y devuelve JSON con shape estable."""

    def _make_app(self) -> FastAPI:
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/raise/notfound")
        async def _raise_notfound() -> None:
            raise NotFoundError("no existe esa cosa")

        @app.get("/raise/forbidden")
        async def _raise_forbidden() -> None:
            raise ForbiddenError("no podés", code="custom_forbidden_code")

        @app.get("/raise/unhandled")
        async def _raise_unhandled() -> None:
            raise ValueError("este NO es DomainError")

        return app

    def test_not_found_returns_404_with_shape(self) -> None:
        client = TestClient(self._make_app())
        resp = client.get("/raise/notfound")
        assert resp.status_code == 404
        assert resp.json() == {"error": "not_found", "detail": "no existe esa cosa"}

    def test_forbidden_with_custom_code(self) -> None:
        client = TestClient(self._make_app())
        resp = client.get("/raise/forbidden")
        assert resp.status_code == 403
        assert resp.json() == {"error": "custom_forbidden_code", "detail": "no podés"}

    def test_unhandled_exception_passes_through(self) -> None:
        # Sin UnhandledExceptionMiddleware montado, las non-DomainError siguen
        # el flujo default de FastAPI (500). El middleware se monta en main.py,
        # no en register_exception_handlers — los tests específicos de ese
        # comportamiento están en TestUnhandledExceptionMiddleware abajo.
        client = TestClient(self._make_app(), raise_server_exceptions=False)
        resp = client.get("/raise/unhandled")
        assert resp.status_code == 500


class TestUnhandledExceptionMiddleware:
    """Regression test del bug "500 enmascarado como CORS error".

    Observado N veces en el dogfood: una excepción Python no controlada
    (Pydantic ValidationError, asyncpg CheckViolationError, RuntimeError, etc.)
    sale como 500 pero SIN header Access-Control-Allow-Origin → browser
    bloquea con "not allowed by access-control-allow-origin", enmascarando
    el bug real.

    Causa: `app.add_exception_handler(Exception, ...)` SÍ captura, pero su
    respuesta NO pasa por la pipeline de middleware de salida. CORS bypasea.
    Fix: middleware custom (BaseHTTPMiddleware) que se ejecuta DENTRO del
    stack y cuya respuesta SÍ pasa por CORSMiddleware al salir.
    """

    def test_500_response_includes_cors_headers(self) -> None:
        from apps.api.core.errors import UnhandledExceptionMiddleware
        from fastapi.middleware.cors import CORSMiddleware

        app = FastAPI()
        register_exception_handlers(app)
        # Orden CRÍTICO: middleware catch-all PRIMERO (innermost), CORS
        # DESPUÉS (outermost). Así el response del catch-all pasa por CORS.
        app.add_middleware(UnhandledExceptionMiddleware)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["https://app.example.com"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

        @app.get("/explode")
        async def _explode() -> None:
            raise RuntimeError("simulated upstream failure")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/explode", headers={"Origin": "https://app.example.com"})

        assert resp.status_code == 500
        # Sin UnhandledExceptionMiddleware, este header sería None → browser
        # bloquea con "CORS not allowed" enmascarando el RuntimeError real.
        assert resp.headers.get("access-control-allow-origin") == "https://app.example.com"
        body = resp.json()
        assert body["error"] == "internal_server_error"

    def test_domain_error_still_uses_its_handler(self) -> None:
        """El middleware re-raise DomainError para que su handler dedicado
        siga procesándolo con shapes y status codes específicos (no genérico 500)."""
        from apps.api.core.errors import UnhandledExceptionMiddleware
        from fastapi.middleware.cors import CORSMiddleware

        app = FastAPI()
        register_exception_handlers(app)
        app.add_middleware(UnhandledExceptionMiddleware)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["https://app.example.com"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

        @app.get("/notfound")
        async def _notfound() -> None:
            raise NotFoundError("X no existe", code="x_not_found")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/notfound", headers={"Origin": "https://app.example.com"})

        assert resp.status_code == 404
        assert resp.json() == {"error": "x_not_found", "detail": "X no existe"}
        assert resp.headers.get("access-control-allow-origin") == "https://app.example.com"
