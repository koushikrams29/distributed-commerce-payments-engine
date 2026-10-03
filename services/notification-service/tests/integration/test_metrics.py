import uuid

from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from sqlalchemy.orm import Session, sessionmaker

from app.services.notification_service import NotificationService


def _sent(channel: str) -> float:
    return REGISTRY.get_sample_value("notifications_sent_total", {"channel": channel}) or 0.0


def test_a_confirmation_is_counted_once_however_often_it_is_requested(
    session_factory: sessionmaker[Session],
) -> None:
    order_id = uuid.uuid4()
    before = _sent("email")

    db = session_factory()
    try:
        service = NotificationService(db)
        service.send_order_confirmation(order_id=order_id)
        service.send_order_confirmation(order_id=order_id)
    finally:
        db.close()

    assert _sent("email") == before + 1


def test_metrics_endpoint_is_exposed(client: TestClient) -> None:
    client.get("/health")

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "http_requests_total" in response.text
