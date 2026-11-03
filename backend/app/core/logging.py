"""Structured JSON logging with defensive PII redaction.

Application code must never log personal data. As a second line of defence the
formatter redacts any ``extra`` field whose name suggests PII or secrets.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

_SENSITIVE_KEYS = (
    "password",
    "token",
    "secret",
    "authorization",
    "mobile",
    "phone",
    "email",
    "name",
    "address",
    "pincode",
    "gotra",
    "sankalp",
    "qr",
)

_STD_ATTRS = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


def _redact(key: str, value: Any) -> Any:
    lowered = key.lower()
    if lowered in {"logger_name"}:
        return value
    if any(s in lowered for s in _SENSITIVE_KEYS):
        return "[REDACTED]"
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STD_ATTRS and not key.startswith("_"):
                data[key] = _redact(key, value)
        if record.exc_info:
            data["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str)


def configure_logging(level: str = "INFO", json_logs: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    if json_logs:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Uvicorn's access log prints full URLs (query strings may contain search terms);
    # we emit our own sanitised access log instead.
    logging.getLogger("uvicorn.access").disabled = True
