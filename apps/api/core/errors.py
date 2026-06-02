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
from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastapi import FastAPI, Request
    from starlette.responses import Response

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


class RateLimitError(DomainError):
    """Demasiadas requests en la ventana de tiempo. Incluye retry_after en segundos."""

    code = "rate_limit_exceeded"
    status_code = 429

    def __init__(self, detail: str, *, retry_after: int = 60) -> None:
        super().__init__(detail)
        self.retry_after = retry_after


class BudgetExceededError(DomainError):
    """El tenant agotó su presupuesto diario de tokens/costo."""

    code = "budget_exceeded"
    status_code = 429

    def __init__(self, detail: str, *, retry_after: int) -> None:
        super().__init__(detail)
        self.retry_after = retry_after


class ExternalIntegrationError(DomainError):
    """Falló una operación contra una integración externa del tenant."""

    code = "external_integration_failed"
    status_code = 502


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
    headers: dict[str, str] = {}
    if isinstance(err, RateLimitError | BudgetExceededError):
        headers["Retry-After"] = str(err.retry_after)
    return JSONResponse(
        status_code=err.status_code,
        content={"error": err.code, "detail": err.detail},
        headers=headers or None,
    )


class UnhandledExceptionMiddleware(BaseHTTPMiddleware):
    """Captura cualquier excepción no manejada y devuelve JSONResponse 500.

    POR QUÉ NO ES UN exception_handler: en Starlette/FastAPI, el handler
    registrado vía `app.add_exception_handler(Exception, ...)` SÍ captura la
    excepción, pero su respuesta NO pasa por la pipeline de middleware de
    salida — específicamente NO pasa por CORSMiddleware. Resultado: el 500
    sale sin header `Access-Control-Allow-Origin` y el browser lo bloquea
    como "not allowed by access-control-allow-origin", enmascarando el bug
    real de Python. (Bug observado N veces en el dogfood: KB 500,
    onboarding 500, Shopify 500, etc.)

    Solución correcta: middleware custom que envuelve TODO. Cuando se monta
    DESPUÉS añadiendo CORSMiddleware (que queda como outermost), la
    respuesta del catch-all pasa por CORS → headers correctos al browser.

    Orden en main.py (importa muchísimo):
        app.add_middleware(UnhandledExceptionMiddleware)  # innermost
        app.add_middleware(CORSMiddleware, ...)           # outermost — añade CORS
                                                          # a TODA respuesta, incluso 500
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        try:
            return await call_next(request)
        except Exception as exc:
            # Re-raise DomainError para que su handler dedicado lo procese
            # (códigos 401/403/404/409/422/429 con shapes específicos).
            if isinstance(exc, DomainError):
                raise
            logger.exception(
                "unhandled_exception path=%s method=%s",
                request.url.path,
                request.method,
                exc_info=exc,
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error": "internal_server_error",
                    "detail": (
                        f"{type(exc).__name__}: {exc!s}"
                        if request.app.debug
                        else "internal_server_error"
                    ),
                },
            )


def register_exception_handlers(app: FastAPI) -> None:
    """Registra los handlers globales de excepción. Llamar una vez en startup.

    - DomainError: errores de negocio con status_code definido (401, 403, 404, 409, 422, 429).

    NOTA sobre el catch-all de Exception: NO está aquí porque `add_exception_handler`
    bypassea el middleware CORS. Para 500s la solución correcta es montar el
    `UnhandledExceptionMiddleware` en main.py (ver docstring del middleware).
    """
    app.add_exception_handler(DomainError, _domain_exception_handler)
