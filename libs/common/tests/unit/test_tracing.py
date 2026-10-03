from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import Decision, TraceIdRatioBased
from opentelemetry.trace import SpanKind

from commerce_common.observability.tracing import (
    SkipUnparentedClientSpans,
    configure_tracing,
    current_trace_context,
    extract_context,
)

tracer = trace.get_tracer(__name__)


def test_no_trace_context_outside_a_span() -> None:
    assert current_trace_context() is None


def test_trace_context_round_trips_through_a_carrier(spans: InMemorySpanExporter) -> None:
    with tracer.start_as_current_span("request") as request_span:
        carrier = current_trace_context()

    assert carrier is not None
    assert carrier["traceparent"].split("-")[1] == format(
        request_span.get_span_context().trace_id, "032x"
    )

    with tracer.start_as_current_span("later work", context=extract_context(carrier)) as later:
        pass

    assert later.get_span_context().trace_id == request_span.get_span_context().trace_id
    assert later.parent is not None
    assert later.parent.span_id == request_span.get_span_context().span_id


def test_extract_accepts_the_bytes_pika_can_deliver(spans: InMemorySpanExporter) -> None:
    with tracer.start_as_current_span("request") as request_span:
        carrier = current_trace_context()
    assert carrier is not None

    as_bytes = {key: value.encode() for key, value in carrier.items()}
    context = extract_context({**as_bytes, "x-retry-count": 2})

    remote = trace.get_current_span(context).get_span_context()
    assert remote.trace_id == request_span.get_span_context().trace_id


def test_configure_tracing_keeps_an_existing_provider() -> None:
    before = trace.get_tracer_provider()
    assert configure_tracing("order-service") is before


def test_unparented_client_spans_are_dropped_but_other_roots_are_kept() -> None:
    sampler = SkipUnparentedClientSpans(TraceIdRatioBased(1.0))

    polling_query = sampler.should_sample(None, 1, "SELECT orders", kind=SpanKind.CLIENT)
    request = sampler.should_sample(None, 1, "GET /orders", kind=SpanKind.SERVER)
    published = sampler.should_sample(None, 1, "order.paid publish", kind=SpanKind.PRODUCER)

    assert polling_query.decision is Decision.DROP
    assert request.decision is Decision.RECORD_AND_SAMPLE
    assert published.decision is Decision.RECORD_AND_SAMPLE
