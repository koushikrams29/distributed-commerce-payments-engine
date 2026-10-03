import threading
from collections.abc import Callable
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode
from prometheus_client import REGISTRY

from commerce_common.messaging import Consumer, publish_event
from commerce_common.messaging.rabbitmq import dead_letter_queue_name
from commerce_common.observability import current_trace_context
from tests.helpers import Recorder, wait_for_queue, wait_until

pytestmark = pytest.mark.integration

tracer = trace.get_tracer(__name__)


class TraceRecorder:
    """Handler that records the trace ID it ran under."""

    def __init__(self) -> None:
        self.trace_ids: list[int] = []
        self._lock = threading.Lock()

    def __call__(self, _routing_key: str, _payload: dict[str, Any]) -> None:
        with self._lock:
            self.trace_ids.append(trace.get_current_span().get_span_context().trace_id)


def _named(spans: InMemorySpanExporter, name: str) -> list[ReadableSpan]:
    return [span for span in spans.get_finished_spans() if span.name == name]


def _consumed(queue: str, routing_key: str, outcome: str) -> float:
    labels = {"queue": queue, "routing_key": routing_key, "outcome": outcome}
    return REGISTRY.get_sample_value("messages_consumed_total", labels) or 0.0


def test_the_handler_runs_inside_the_publishers_trace(
    rabbitmq_url: str,
    names: tuple[str, str],
    start: Callable[..., Consumer],
    spans: InMemorySpanExporter,
) -> None:
    queue, routing_key = names
    handler = TraceRecorder()
    start(queue_name=queue, routing_keys=[routing_key], handler=handler)
    wait_for_queue(rabbitmq_url, dead_letter_queue_name(queue))

    with tracer.start_as_current_span("POST /orders") as request:
        publish_event(rabbitmq_url, routing_key, {"order_id": "o-1"})

    wait_until(lambda: len(handler.trace_ids) == 1)
    trace_id = request.get_span_context().trace_id
    assert handler.trace_ids == [trace_id]

    wait_until(lambda: bool(_named(spans, f"{routing_key} process")))
    (publish,) = _named(spans, f"{routing_key} publish")
    (process,) = _named(spans, f"{routing_key} process")
    assert publish.kind is SpanKind.PRODUCER
    assert process.kind is SpanKind.CONSUMER
    assert publish.parent is not None and publish.parent.span_id == request.get_span_context().span_id
    assert process.parent is not None and process.parent.span_id == publish.context.span_id
    assert process.attributes["messaging.destination.name"] == queue


def test_a_saved_trace_context_wins_over_the_current_one(
    rabbitmq_url: str,
    names: tuple[str, str],
    start: Callable[..., Consumer],
    spans: InMemorySpanExporter,
) -> None:
    """The outbox relay publishes long after the request ended, from its own loop."""
    queue, routing_key = names
    handler = TraceRecorder()
    start(queue_name=queue, routing_keys=[routing_key], handler=handler)
    wait_for_queue(rabbitmq_url, dead_letter_queue_name(queue))

    with tracer.start_as_current_span("POST /orders") as request:
        saved = current_trace_context()
    with tracer.start_as_current_span("outbox relay poll"):
        publish_event(rabbitmq_url, routing_key, {"order_id": "o-2"}, trace_context=saved)

    wait_until(lambda: len(handler.trace_ids) == 1)
    assert handler.trace_ids == [request.get_span_context().trace_id]


def test_every_retry_joins_the_original_trace_and_records_the_error(
    rabbitmq_url: str,
    names: tuple[str, str],
    start: Callable[..., Consumer],
    spans: InMemorySpanExporter,
) -> None:
    queue, routing_key = names
    handler = Recorder(fail_times=1)
    start(queue_name=queue, routing_keys=[routing_key], handler=handler,
          retry_delays_seconds=(0.2,))
    wait_for_queue(rabbitmq_url, dead_letter_queue_name(queue))
    retried_before = _consumed(queue, routing_key, "retried")
    succeeded_before = _consumed(queue, routing_key, "success")

    with tracer.start_as_current_span("POST /orders") as request:
        publish_event(rabbitmq_url, routing_key, {"order_id": "o-3"})

    wait_until(lambda: len(_named(spans, f"{routing_key} process")) == 2)
    attempts = sorted(
        _named(spans, f"{routing_key} process"),
        key=lambda span: span.attributes["messaging.rabbitmq.retry_count"],
    )
    assert {span.context.trace_id for span in attempts} == {request.get_span_context().trace_id}
    assert attempts[0].status.status_code is StatusCode.ERROR
    assert attempts[0].events[0].name == "exception"
    assert attempts[1].status.status_code is not StatusCode.ERROR
    assert _consumed(queue, routing_key, "retried") == retried_before + 1
    assert _consumed(queue, routing_key, "success") == succeeded_before + 1


def test_dead_lettered_messages_are_counted(
    rabbitmq_url: str, names: tuple[str, str], start: Callable[..., Consumer]
) -> None:
    queue, routing_key = names
    start(queue_name=queue, routing_keys=[routing_key], handler=Recorder(fail_times=99),
          retry_delays_seconds=())
    wait_for_queue(rabbitmq_url, dead_letter_queue_name(queue))

    publish_event(rabbitmq_url, routing_key, {"order_id": "o-4"})

    wait_until(lambda: _consumed(queue, routing_key, "dead_lettered") == 1)
    published = REGISTRY.get_sample_value(
        "messages_published_total", {"routing_key": routing_key}
    )
    assert published == 1
