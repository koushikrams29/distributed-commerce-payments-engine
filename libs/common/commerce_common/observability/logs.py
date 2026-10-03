import json
import logging
from datetime import UTC, datetime
from typing import Literal

from opentelemetry import trace

TEXT_FORMAT = "%(asctime)s %(levelname)s [%(name)s] [trace=%(trace_id)s] %(message)s"

# Libraries that log every connection open/close at INFO. Their warnings
# (lost connections, retries) still get through.
NOISY_LOGGERS = ("pika", "httpx", "httpcore")


class TraceContextFilter(logging.Filter):
    """Stamps every record with the active trace and span IDs (empty outside a trace)."""

    def filter(self, record: logging.LogRecord) -> bool:
        context = trace.get_current_span().get_span_context()
        record.trace_id = format(context.trace_id, "032x") if context.is_valid else ""
        record.span_id = format(context.span_id, "016x") if context.is_valid else ""
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, so log platforms can index fields, not grep text."""

    def __init__(self, service_name: str) -> None:
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service_name,
        }
        trace_id = getattr(record, "trace_id", "")
        if trace_id:
            entry["trace_id"] = trace_id
            entry["span_id"] = getattr(record, "span_id", "")
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(
    service_name: str,
    *,
    log_format: Literal["text", "json"] = "text",
    level: str = "INFO",
) -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_commerce_handler", False):
            root.removeHandler(handler)

    handler = logging.StreamHandler()
    handler._commerce_handler = True  # type: ignore[attr-defined]
    handler.addFilter(TraceContextFilter())
    handler.setFormatter(
        JsonFormatter(service_name) if log_format == "json" else logging.Formatter(TEXT_FORMAT)
    )
    root.addHandler(handler)
    root.setLevel(level.upper())
    # At DEBUG the chatter is wanted; at WARNING and above they inherit the root level.
    quiet = root.level == logging.INFO
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING if quiet else logging.NOTSET)

    if log_format == "json":
        # uvicorn installs its own plain-text handlers; route its records
        # through ours so every line a container prints is JSON.
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            uvicorn_logger = logging.getLogger(name)
            uvicorn_logger.handlers.clear()
            uvicorn_logger.propagate = True
