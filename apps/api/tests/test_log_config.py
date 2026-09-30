"""Logging JSON para Cloud Run: severidad reconocible + campos `extra`.

Antes, `logger.error(...)` sin traceback llegaba a Cloud Logging con severidad vacía
→ una alerta `severity>=ERROR` no lo veía, y los `extra` (tenant_id…) se perdían.
"""

from __future__ import annotations

import json
import logging

import pytest
from apps.api.core.log_config import CloudRunJsonFormatter, configure_logging


def _record(level: int, msg: str, **extra: object) -> logging.LogRecord:
    logger = logging.getLogger("apps.api.test")
    record = logger.makeRecord("apps.api.test", level, __file__, 1, msg, (), None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_error_line_has_severity_and_extra_fields() -> None:
    line = CloudRunJsonFormatter().format(
        _record(logging.ERROR, "inbound_turn_graph_error", tenant_id="t-1", job_id="j-1")
    )
    payload = json.loads(line)
    assert payload["severity"] == "ERROR"
    assert payload["message"] == "inbound_turn_graph_error"
    assert payload["logger"] == "apps.api.test"
    assert (payload["tenant_id"], payload["job_id"]) == ("t-1", "j-1")
    assert "levelname" not in payload and "msg" not in payload


def test_exception_traceback_goes_into_message() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = _record(logging.ERROR, "inbound_job_failed")
        record.exc_info = sys.exc_info()
    payload = json.loads(CloudRunJsonFormatter().format(record))
    assert payload["message"].startswith("inbound_job_failed\nTraceback")
    assert "ValueError: boom" in payload["message"]


def test_non_serializable_extra_does_not_break_logging() -> None:
    payload = json.loads(CloudRunJsonFormatter().format(_record(logging.INFO, "x", obj=object())))
    assert payload["obj"].startswith("<object object")


def test_json_only_on_cloud_run(monkeypatch: pytest.MonkeyPatch) -> None:
    root = logging.getLogger()
    saved = (root.handlers[:], root.level)
    try:
        monkeypatch.delenv("K_SERVICE", raising=False)
        configure_logging("INFO")
        assert not isinstance(root.handlers[0].formatter, CloudRunJsonFormatter)

        monkeypatch.setenv("K_SERVICE", "auyan-api-staging")
        configure_logging("INFO")
        assert isinstance(root.handlers[0].formatter, CloudRunJsonFormatter)
        assert logging.getLogger("uvicorn.error").propagate is True
    finally:
        root.handlers, root.level = saved[0], saved[1]
