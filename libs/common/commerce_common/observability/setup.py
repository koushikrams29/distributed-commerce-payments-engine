import importlib.util
from collections.abc import Sequence
from typing import TYPE_CHECKING

from commerce_common.observability.logs import configure_logging
from commerce_common.observability.metrics import PrometheusMiddleware, metrics_endpoint
from commerce_common.observability.settings import ObservabilitySettings
from commerce_common.observability.tracing import configure_tracing

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.engine import Engine

_UNTRACED_PATHS = ("health", "metrics")


def setup_observability(
    app: "FastAPI",
    *,
    service_name: str,
    settings: ObservabilitySettings,
    engine: "Engine | None" = None,
    untraced_paths: Sequence[str] = (),
) -> None:
    """Logs with trace IDs, OpenTelemetry tracing, and a Prometheus `/metrics` endpoint."""
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    configure_logging(service_name, log_format=settings.log_format, level=settings.log_level)
    configure_tracing(
        service_name,
        otlp_endpoint=settings.otel_exporter_otlp_endpoint,
        sample_ratio=settings.trace_sample_ratio,
    )

    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls=",".join((*_UNTRACED_PATHS, *untraced_paths)),
        # The ASGI send/receive sub-spans add two spans per request and no insight.
        exclude_spans=["receive", "send"],
    )
    _instrument_httpx()
    if engine is not None:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        sqlalchemy_instrumentor = SQLAlchemyInstrumentor()
        if not sqlalchemy_instrumentor.is_instrumented_by_opentelemetry:
            sqlalchemy_instrumentor.instrument(engine=engine)

    app.add_middleware(PrometheusMiddleware)
    app.add_route("/metrics", metrics_endpoint, include_in_schema=False)


def _instrument_httpx() -> None:
    # Only services that call other services install httpx; without this check
    # the instrumentor logs an ERROR at every startup of the others.
    if importlib.util.find_spec("httpx") is None:
        return
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    instrumentor = HTTPXClientInstrumentor()
    if not instrumentor.is_instrumented_by_opentelemetry:
        # Outgoing calls carry `traceparent`, so the next service joins the trace.
        instrumentor.instrument()
