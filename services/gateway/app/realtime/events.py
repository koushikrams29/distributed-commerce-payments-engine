from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace

from commerce_common.messaging import run_consumer

from app.core.config import settings
from app.realtime.hub import DashboardHub


def current_trace_id() -> str | None:
    """Trace ID of the active span, or None when there is no valid one."""
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else None


def relay_message(hub: DashboardHub, routing_key: str, payload: dict[str, Any]) -> None:
    # The consumer runs this inside a span continued from the publisher's
    # trace headers, so the current trace is the one that produced the event.
    hub.publish(
        {
            "type": routing_key,
            "data": payload,
            "received_at": datetime.now(UTC).isoformat(),
            "trace_id": current_trace_id(),
        }
    )


def start_dashboard_event_relay(hub: DashboardHub) -> None:
    """Forward every domain event to connected dashboards.

    Uses a private queue (`queue_name=None`) so each Gateway instance receives
    every event for its own connected admins; if the Gateway restarts, the
    dashboard reloads its snapshot over HTTP, so nothing needs to be durable.
    """
    run_consumer(
        url=settings.rabbitmq_url,
        queue_name=None,
        routing_keys=["#"],
        handler=lambda routing_key, payload: relay_message(hub, routing_key, payload),
    )
