from collections.abc import Mapping, Sequence
from typing import Any

from opentelemetry import propagate, trace
from opentelemetry.context import Context
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import (
    Decision,
    ParentBased,
    Sampler,
    SamplingResult,
    TraceIdRatioBased,
)
from opentelemetry.trace import Link, SpanKind
from opentelemetry.util.types import Attributes


class SkipUnparentedClientSpans(Sampler):
    """Drops client spans that would start a new trace.

    A database query or HTTP call with no parent span comes from a background
    poller (the outbox relay every second, the reconciler every minute), not
    from work anyone asked for. Tracing those would bury real traces in noise.
    Used only as the root sampler, so client spans inside a request or message
    trace are unaffected.
    """

    def __init__(self, delegate: Sampler) -> None:
        self._delegate = delegate

    def should_sample(
        self,
        parent_context: Context | None,
        trace_id: int,
        name: str,
        kind: SpanKind | None = None,
        attributes: Attributes = None,
        links: Sequence[Link] | None = None,
        trace_state: Any = None,
    ) -> SamplingResult:
        if kind == SpanKind.CLIENT:
            return SamplingResult(Decision.DROP)
        return self._delegate.should_sample(
            parent_context, trace_id, name, kind, attributes, links, trace_state
        )

    def get_description(self) -> str:
        return f"SkipUnparentedClientSpans{{{self._delegate.get_description()}}}"


def configure_tracing(
    service_name: str,
    *,
    otlp_endpoint: str | None = None,
    sample_ratio: float = 1.0,
) -> trace.TracerProvider:
    """Install the process-wide tracer provider (once; later calls are no-ops)."""
    current = trace.get_tracer_provider()
    if isinstance(current, TracerProvider):
        return current

    provider = TracerProvider(
        resource=Resource.create({SERVICE_NAME: service_name}),
        sampler=ParentBased(root=SkipUnparentedClientSpans(TraceIdRatioBased(sample_ratio))),
    )
    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=f"{otlp_endpoint.rstrip('/')}/v1/traces")
            )
        )
    trace.set_tracer_provider(provider)
    return provider


def current_trace_context() -> dict[str, str] | None:
    """The active trace context as W3C headers (`traceparent`), or None outside a trace.

    Stored alongside work that runs later — such as an outbox row — so the
    later work joins the trace that caused it.
    """
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return carrier or None


def extract_context(carrier: Mapping[str, Any] | None) -> Context:
    """Rebuild a trace context from message headers or a stored carrier."""
    normalized: dict[str, str] = {}
    for key, value in (carrier or {}).items():
        if isinstance(value, bytes):
            normalized[key] = value.decode("utf-8", errors="replace")
        elif isinstance(value, str):
            normalized[key] = value
    return propagate.extract(normalized)
