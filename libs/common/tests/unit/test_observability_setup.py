import importlib.util
import logging

import pytest
from fastapi import FastAPI
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from commerce_common.observability import ObservabilitySettings, setup_observability


def test_services_without_httpx_start_without_instrumentation_errors(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    real_find_spec = importlib.util.find_spec

    def find_spec_without_httpx(name: str, *args: object) -> object:
        return None if name == "httpx" else real_find_spec(name, *args)

    def fail_instrument(self: HTTPXClientInstrumentor, **kwargs: object) -> None:
        pytest.fail("httpx was instrumented although it is not installed")

    monkeypatch.setattr(importlib.util, "find_spec", find_spec_without_httpx)
    # Another test may already have instrumented httpx process-wide.
    monkeypatch.setattr(HTTPXClientInstrumentor, "is_instrumented_by_opentelemetry", False)
    monkeypatch.setattr(HTTPXClientInstrumentor, "instrument", fail_instrument)

    with caplog.at_level(logging.ERROR):
        setup_observability(
            FastAPI(), service_name="no-httpx-service", settings=ObservabilitySettings()
        )

    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]
