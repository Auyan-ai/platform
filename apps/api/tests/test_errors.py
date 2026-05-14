"""Tests para core.errors: las excepciones de dominio y su handler global."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.core.errors import (
    ConflictError,
    DomainError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationFailed,
    register_exception_handlers,
)


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
    def test_defaults(self, cls: type[DomainError], expected_code: str, expected_status: int) -> None:
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
        # Las que no son DomainError siguen el flujo default de FastAPI (500).
        # TestClient propaga la excepción salvo que se diga lo contrario.
        client = TestClient(self._make_app(), raise_server_exceptions=False)
        resp = client.get("/raise/unhandled")
        assert resp.status_code == 500
