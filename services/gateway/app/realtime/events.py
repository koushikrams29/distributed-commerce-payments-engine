from datetime import UTC, datetime
from typing import Any

from commerce_common.messaging import run_consumer

from app.core.config import settings
from app.realtime.hub import DashboardHub


def start_dashboard_event_relay(hub: DashboardHub) -> None:
    """Forward every domain event to connected dashboards.

    Uses a private queue (`queue_name=None`) so each Gateway instance receives
    every event for its own connected admins; if the Gateway restarts, the
    dashboard reloads its snapshot over HTTP, so nothing needs to be durable.
    """

    def relay(routing_key: str, payload: dict[str, Any]) -> None:
        hub.publish(
            {
                "type": routing_key,
                "data": payload,
                "received_at": datetime.now(UTC).isoformat(),
            }
        )

    run_consumer(
        url=settings.rabbitmq_url,
        queue_name=None,
        routing_keys=["#"],
        handler=relay,
    )
