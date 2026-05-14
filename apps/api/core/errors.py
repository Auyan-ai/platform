"""Excepciones de dominio + handlers HTTP.

Los services nunca importan FastAPI. Lanzan estas excepciones; el handler
global registrado en `main.py` las traduce a JSON con status code correcto.
Así el dominio queda testeable sin FastAPI y los routers no necesitan
intercambiar HTTPException por todos lados.

Forma del response body:
    {"error": "<code>", "detail": "<mensaje legible>"}
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------
# Excepciones de dominio
# ----------------------------------------------------------------


class DomainError(Exception):
    """Base de errores de dominio. No instanciar directo — usar las subclases."""

    code: str = "domain_error"
    status_code: int = 500

    def __init__(self, detail: str, *, code: str | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        if code is not None:
            self.code = code


class UnauthorizedError(DomainError):
    """Credenciales ausentes, inválidas o expiradas."""

    code = "unauthorized"
    status_code = 401


class ForbiddenError(DomainError):
    """Autenticado, pero sin permiso para esta acción/recurso."""

    code = "forbidden"
    status_code = 403


class NotFoundError(DomainError):
    """El recurso no existe (o el caller no puede verlo dentro de su tenant)."""

    code = "not_found"
    status_code = 404


class ConflictError(DomainError):
    """Conflicto con el estado actual (ej. escalation ya claimed)."""

    code = "conflict"
    status_code = 409


class ValidationFailed(DomainError):
    """Validación de negocio (no de schema). Schema lo cubre Pydantic/FastAPI."""

    code = "validation_failed"
    status_code = 422


# ----------------------------------------------------------------
# Handler registration
# ----------------------------------------------------------------


async def _domain_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Registrado solo para DomainError → el cast es seguro.
    err = cast("DomainError", exc)
    log_extra = {"path": request.url.path, "code": err.code}
    if err.status_code >= 500:
        logger.error("domain_error %s: %s", err.code, err.detail, extra=log_extra)
    else:
        logger.warning("domain_error %s: %s", err.code, err.detail, extra=log_extra)
    return JSONResponse(
        status_code=err.status_code,
        content={"error": err.code, "detail": err.detail},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Registra el handler global de DomainError. Llamar una vez en startup."""
    app.add_exception_handler(DomainError, _domain_exception_handler)
