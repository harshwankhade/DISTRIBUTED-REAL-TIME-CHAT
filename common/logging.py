"""Small JSON logging setup shared by all processes."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any


_STANDARD_FIELDS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Format logs as one JSON object per line for simple aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_FIELDS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


class ContextLoggerAdapter(logging.LoggerAdapter):
    """Preserve process context while allowing event-specific structured fields."""

    def process(
        self, msg: object, kwargs: dict[str, Any]
    ) -> tuple[object, dict[str, Any]]:
        merged_extra = dict(self.extra or {})
        supplied_extra = kwargs.get("extra")
        if isinstance(supplied_extra, dict):
            merged_extra.update(supplied_extra)
        kwargs["extra"] = merged_extra
        return msg, kwargs


def configure_logging(*, service: str, node_id: str, level: str) -> ContextLoggerAdapter:
    """Configure process logging and return a logger with stable identity fields."""

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    logger = logging.getLogger(service)
    return ContextLoggerAdapter(logger, {"service": service, "node_id": node_id})
