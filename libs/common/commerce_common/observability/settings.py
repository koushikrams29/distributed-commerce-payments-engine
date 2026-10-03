from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class ObservabilitySettings(BaseSettings):
    """Base class for every service's Settings, so the same variables work everywhere."""

    # e.g. http://localhost:4318 — unset means spans are created (logs still
    # carry trace IDs) but not exported anywhere.
    otel_exporter_otlp_endpoint: str | None = None
    # Share of new traces kept; a request joining an existing trace follows
    # its parent's decision so traces are never half-recorded.
    trace_sample_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    log_format: Literal["text", "json"] = "text"
    log_level: str = "INFO"
