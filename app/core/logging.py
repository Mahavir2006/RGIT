"""Structured logging with request/run correlation and mandatory secret redaction.

Design:

* One JSON line per record in production, human-readable in development.
* A contextvar carries the current correlation id so any log call inside a request or an
  ingestion run is automatically attributable without threading a logger through call sites.
* Every message and every structured field passes through the secret redactor before emission.
  Redaction happens in a :class:`logging.Filter` so it cannot be bypassed by accident.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

from app.core.config import Settings, get_settings
from app.core.security import redactor
from app.core.timeutil import utc_now

__all__ = [
    "configure_logging",
    "get_logger",
    "correlation_id_var",
    "new_correlation_id",
    "request_context",
    "bind_context",
    "clear_context",
]

# Correlation id for the current unit of work (HTTP request or ingestion run).
correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)
# Optional secondary identifier, e.g. the source being ingested.
source_id_var: ContextVar[str | None] = ContextVar("source_id", default=None)

# Attributes present on every LogRecord by default; anything else is treated as a structured field.
_RESERVED = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName", "levelname",
    "levelno", "lineno", "module", "msecs", "message", "msg", "name", "pathname", "process",
    "processName", "relativeCreated", "stack_info", "thread", "threadName", "taskName",
}

# Context fields this module adds itself, which must not be re-scrubbed as user extras.
_PRESERVED = {"correlation_id", "source_id", "service"}


class CorrelationFilter(logging.Filter):
    """Injects correlation context and scrubs secrets from every emitted record.

    Scrubbing happens here, once, at the record level — not in each formatter. That way no
    formatter can bypass it, and no raw secret is ever retained on the record.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id_var.get() or "-"
        record.source_id = source_id_var.get() or "-"
        record.service = get_settings().app_name

        # Scrub the message itself; adapters may interpolate upstream text.
        try:
            record.msg = redactor.scrub_text(record.getMessage())
            record.args = ()
        except Exception:  # pragma: no cover - defensive, never break logging
            record.msg = "<log formatting failed>"
            record.args = ()

        # Scrub structured extras too. A caller logging a URL or a provider response object would
        # otherwise leave the raw value on the record for the formatter to print.
        for key in list(record.__dict__):
            if key in _RESERVED or key in _PRESERVED or key.startswith("_"):
                continue
            try:
                record.__dict__[key] = redactor.scrub(record.__dict__[key])
            except Exception:  # pragma: no cover - defensive
                record.__dict__[key] = "<redacted>"

        return True


class JsonFormatter(logging.Formatter):
    """Render a log record as a single JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": utc_now().isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": getattr(record, "msg", ""),
            "correlation_id": getattr(record, "correlation_id", "-"),
            "source_id": getattr(record, "source_id", "-"),
            "service": getattr(record, "service", "urban-sentinel"),
        }
        # Structured extras supplied via logger.info("msg", extra={...}).
        for key, value in record.__dict__.items():
            if key in _RESERVED or key in payload:
                continue
            if key.startswith("_") or key in _PRESERVED:
                continue
            payload[key] = value
        if record.exc_info:
            payload["exception"] = redactor.scrub_text(self.formatException(record.exc_info))
        try:
            return json.dumps(payload, default=str, ensure_ascii=False)
        except Exception:  # pragma: no cover - defensive
            return json.dumps({"level": record.levelname, "message": "log serialisation failed"})


class ConsoleFormatter(logging.Formatter):
    """Compact, human-readable single-line output for local development."""

    def format(self, record: logging.LogRecord) -> str:
        cid = getattr(record, "correlation_id", "-")
        prefix = f"[{record.levelname:<8}] [{cid:<8}]"
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED
            and key not in _PRESERVED
            and not key.startswith("_")
        }
        base = f"{prefix} {record.name}: {getattr(record, 'msg', '')}"
        if extras:
            base += " " + " ".join(f"{k}={v}" for k, v in extras.items())
        if record.exc_info:
            base += "\n" + redactor.scrub_text(self.formatException(record.exc_info))
        return base


def configure_logging(settings: Settings | None = None) -> None:
    """Install the root logging handler. Idempotent."""
    current = settings or get_settings()
    redactor.register_from_settings(current)

    root = logging.getLogger()
    root.setLevel(current.effective_log_level())

    # Replace our own handler so repeated calls (tests, reloads) do not duplicate output.
    for handler in list(root.handlers):
        if getattr(handler, "_urban_sentinel_handler", False):
            root.removeHandler(handler)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter() if current.log_format == "json" else ConsoleFormatter())
    handler.addFilter(CorrelationFilter())
    handler._urban_sentinel_handler = True  # type: ignore[attr-defined]
    root.addHandler(handler)

    # Uvicorn duplicates access logs through its own handlers; route them through ours.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers = []
        uv_logger.propagate = True

    # SQLAlchemy echo can print bound parameters, which may embed credentials.
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if current.db_echo else logging.WARNING
    )


def get_logger(name: str) -> logging.Logger:
    """Return a module logger."""
    return logging.getLogger(name)


def new_correlation_id(prefix: str = "req") -> str:
    """Generate a short, sortable, unique correlation id."""
    import uuid

    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def bind_context(correlation_id: str | None = None, source_id: str | None = None):
    """Bind correlation context for the current task and return reset tokens."""
    tokens = []
    if correlation_id is not None:
        tokens.append((correlation_id_var, correlation_id_var.set(correlation_id)))
    if source_id is not None:
        tokens.append((source_id_var, source_id_var.set(source_id)))
    return tokens


def clear_context(tokens: list) -> None:
    """Reset contextvars previously bound by :func:`bind_context`."""
    for var, token in tokens or []:
        var.reset(token)


class request_context:  # noqa: N801 - used as a context manager, reads like a verb
    """Context manager binding a correlation id (and optionally a source id) for a block.

    Example:
        >>> with request_context("run_abc", source_id="weather.live") as cid:
        ...     get_logger(__name__).info("fetching")
    """

    def __init__(self, correlation_id: str | None = None, *, source_id: str | None = None,
                 prefix: str = "req") -> None:
        self.correlation_id = correlation_id or new_correlation_id(prefix)
        self.source_id = source_id
        self._tokens: list = []

    def __enter__(self) -> str:
        self._tokens = bind_context(self.correlation_id, self.source_id)
        return self.correlation_id

    def __exit__(self, *exc_info: object) -> None:
        clear_context(self._tokens)
        self._tokens = []
