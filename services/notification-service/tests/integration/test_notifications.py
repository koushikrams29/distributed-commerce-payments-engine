import uuid

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.models import NotificationStatus
from app.services.notification_service import NotificationService


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_send_order_confirmation_persists_notification(
    session_factory: sessionmaker[Session], engine: Engine
) -> None:
    order_id = uuid.uuid4()
    db = session_factory()
    try:
        notification, created = NotificationService(db).send_order_confirmation(
            order_id=order_id,
            payment_id=uuid.uuid4(),
        )
        assert created is True
        assert notification.status == NotificationStatus.SENT.value
        assert notification.channel == "email"
    finally:
        db.close()

    with engine.connect() as connection:
        count = connection.execute(
            text("SELECT COUNT(*) FROM notifications WHERE order_id = :id"),
            {"id": order_id},
        ).scalar_one()
        assert count == 1


def test_send_order_confirmation_is_idempotent(
    session_factory: sessionmaker[Session],
) -> None:
    order_id = uuid.uuid4()
    db = session_factory()
    try:
        service = NotificationService(db)
        first, created_first = service.send_order_confirmation(order_id=order_id)
        second, created_second = service.send_order_confirmation(order_id=order_id)
        assert created_first is True
        assert created_second is False
        assert first.id == second.id
    finally:
        db.close()
