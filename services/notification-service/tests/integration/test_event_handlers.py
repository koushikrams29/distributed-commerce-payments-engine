import uuid

import pytest
from commerce_common.events import EventType
from sqlalchemy.orm import Session, sessionmaker

from app.events import consumers
from app.services.notification_service import NotificationService


@pytest.fixture(autouse=True)
def use_test_database(
    monkeypatch: pytest.MonkeyPatch, session_factory: sessionmaker[Session]
) -> None:
    monkeypatch.setattr(consumers, "SessionLocal", session_factory)


def _notifications(session_factory: sessionmaker[Session], order_id: uuid.UUID) -> int:
    with session_factory() as db:
        return len(NotificationService(db).list_for_order(order_id))


def test_fulfilled_order_gets_one_confirmation_even_when_redelivered(
    session_factory: sessionmaker[Session],
) -> None:
    order_id = uuid.uuid4()

    consumers._handle_order_fulfilled(EventType.ORDER_FULFILLED, {"order_id": str(order_id)})
    consumers._handle_order_fulfilled(EventType.ORDER_FULFILLED, {"order_id": str(order_id)})

    assert _notifications(session_factory, order_id) == 1


def test_events_from_old_bindings_are_ignored(session_factory: sessionmaker[Session]) -> None:
    order_id = uuid.uuid4()

    # Queues created before the consumer moved to order.fulfilled are still
    # bound to payment.succeeded; a paid order is not yet a fulfilled one.
    consumers._handle_order_fulfilled(EventType.PAYMENT_SUCCEEDED, {"order_id": str(order_id)})

    assert _notifications(session_factory, order_id) == 0
