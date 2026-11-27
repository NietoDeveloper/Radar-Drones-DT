"""Logging: text or structured JSON, with a per-request correlation id."""

from __future__ import annotations

import contextvars
import json
import logging
import sys

request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": round(record.created, 3), "level": record.levelname, "logger": record.name,
               "msg": record.getMessage(), "request_id": request_id.get()}
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, separators=(",", ":"))


def configure_logging(fmt: str = "text", level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if fmt == "json" else logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"))
    def _stamp(record: logging.LogRecord) -> bool:
        record.request_id = request_id.get()
        return True

    handler.addFilter(_stamp)
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING if fmt == "json" else logging.INFO)
