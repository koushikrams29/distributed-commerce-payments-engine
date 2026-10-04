import uuid

import pytest
from commerce_common.events import EventType
from sqlalchemy.orm import Session, sessionmaker

from app.events import consumers
from app.services.recommendation_service import RecommendationService


@pytest.fixture(autouse=True)
def use_test_database(
    monkeypatch: pytest.MonkeyPatch, session_factory: sessionmaker[Session]
) -> None:
    monkeypatch.setattr(consumers, "SessionLocal", session_factory)


def _paid(order_id: uuid.UUID, *product_ids: uuid.UUID) -> dict[str, object]:
    return {
        "order_id": str(order_id),
        "items": [{"product_id": str(product_id), "qty": 1} for product_id in product_ids],
    }


def _recommended_for(
    session_factory: sessionmaker[Session], product_id: uuid.UUID
) -> list[dict[str, object]]:
    with session_factory() as db:
        return RecommendationService(db).get_recommendations(product_id)


def test_paid_order_records_co_purchases_once(session_factory: sessionmaker[Session]) -> None:
    order_id, keyboard, mouse = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    consumers._handle_payment_succeeded(EventType.PAYMENT_SUCCEEDED, _paid(order_id, keyboard, mouse))
    consumers._handle_payment_succeeded(EventType.PAYMENT_SUCCEEDED, _paid(order_id, keyboard, mouse))

    assert _recommended_for(session_factory, keyboard) == [
        {"product_id": str(mouse), "co_purchase_count": 1}
    ]


def test_payment_without_items_is_skipped(session_factory: sessionmaker[Session]) -> None:
    product_id = uuid.uuid4()

    consumers._handle_payment_succeeded(
        EventType.PAYMENT_SUCCEEDED, {"order_id": str(uuid.uuid4()), "items": []}
    )

    assert _recommended_for(session_factory, product_id) == []
