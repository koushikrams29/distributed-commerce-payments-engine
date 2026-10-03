import json
import logging
from collections.abc import Iterator

import pytest
from opentelemetry import trace

from commerce_common.observability.logs import (
    NOISY_LOGGERS,
    JsonFormatter,
    TraceContextFilter,
    configure_logging,
)

tracer = trace.get_tracer(__name__)


def _record(message: str = "charged order", exc_info: object = None) -> logging.LogRecord:
    record = logging.LogRecord(
        name="app.payments", level=logging.INFO, pathname=__file__, lineno=1,
        msg=message, args=(), exc_info=exc_info,  # type: ignore[arg-type]
    )
    TraceContextFilter().filter(record)
    return record


def test_json_lines_carry_the_active_trace_id() -> None:
    with tracer.start_as_current_span("charge") as span:
        line = JsonFormatter("payment-service").format(_record())

    entry = json.loads(line)
    context = span.get_span_context()
    assert entry["message"] == "charged order"
    assert entry["service"] == "payment-service"
    assert entry["level"] == "INFO"
    assert entry["trace_id"] == format(context.trace_id, "032x")
    assert entry["span_id"] == format(context.span_id, "016x")


def test_json_lines_outside_a_trace_omit_trace_fields() -> None:
    entry = json.loads(JsonFormatter("payment-service").format(_record()))
    assert "trace_id" not in entry


def test_exceptions_are_included_as_one_field() -> None:
    try:
        raise ValueError("card declined")
    except ValueError:
        import sys

        record = _record("charge failed", exc_info=sys.exc_info())

    entry = json.loads(JsonFormatter("payment-service").format(record))
    assert "ValueError: card declined" in entry["exception"]


@pytest.fixture
def restore_root_logger() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.NOTSET)


@pytest.mark.usefixtures("restore_root_logger")
def test_connection_chatter_is_hidden_at_info_but_not_at_debug() -> None:
    pika = logging.getLogger("pika")

    configure_logging("test", level="INFO")
    assert not pika.isEnabledFor(logging.INFO)
    assert pika.isEnabledFor(logging.WARNING)

    configure_logging("test", level="DEBUG")
    assert pika.isEnabledFor(logging.DEBUG)
