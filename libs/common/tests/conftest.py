from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

# The tracer provider can only be installed once per process, so tests share
# one that records spans in memory; configure_tracing() leaves it in place.
_span_exporter = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(_span_exporter))
trace.set_tracer_provider(_provider)


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    _span_exporter.clear()
    yield _span_exporter
    _span_exporter.clear()


@pytest.fixture(scope="session")
def rabbitmq_url() -> Iterator[str]:
    from testcontainers.community.rabbitmq import RabbitMqContainer

    # Same image as infra/docker-compose.yml.
    with RabbitMqContainer("rabbitmq:3-management") as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(5672)
        yield f"amqp://guest:guest@{host}:{port}/"
