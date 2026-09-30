"""Configuración de logging: JSON estructurado en Cloud Run, texto en local.

Cloud Run solo entiende la severidad de una línea si es JSON con campo `severity`.
Con el formato de texto, un `logger.error("inbound_turn_graph_error", …)` llegaba a
Cloud Logging con severidad vacía (solo los tracebacks se reconocían como ERROR), así
que una alerta `severity>=ERROR` no lo veía. Además los campos `extra` (tenant_id,
conversation_id, job_id, decision…) se descartaban.

En Cloud Run (variable `K_SERVICE`) cada registro sale como una línea JSON:
    {"severity": "ERROR", "message": "…", "logger": "…", "tenant_id": "…", …}
Si hay excepción, su traceback se añade al `message` para que Error Reporting agrupe
el error.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from datetime import UTC, datetime
from typing import Any

# Atributos estándar de LogRecord: todo lo demás viene de `extra=`.
_STANDARD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys()
    | {"message", "asctime", "taskName"}
)

# Loggers de uvicorn que traen sus propios handlers de texto.
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


class CloudRunJsonFormatter(logging.Formatter):
    """Una línea JSON por registro con `severity` (formato de Cloud Logging)."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        if record.exc_info:
            message = f"{message}\n{''.join(traceback.format_exception(*record.exc_info))}"
        elif record.stack_info:
            message = f"{message}\n{record.stack_info}"
        payload: dict[str, Any] = {
            "severity": record.levelname,
            "message": message,
            "logger": record.name,
            "time": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


def running_on_cloud_run() -> bool:
    return bool(os.environ.get("K_SERVICE"))


def configure_logging(level: str) -> None:
    """Configura el root logger (y uvicorn). JSON en Cloud Run, texto en local."""
    handler = logging.StreamHandler(sys.stdout)
    if running_on_cloud_run():
        handler.setFormatter(CloudRunJsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    if running_on_cloud_run():
        # uvicorn configura sus handlers de texto antes del lifespan: se reencaminan
        # al root para que sus errores también lleven severidad.
        for name in _UVICORN_LOGGERS:
            uv = logging.getLogger(name)
            uv.handlers = []
            uv.propagate = True
