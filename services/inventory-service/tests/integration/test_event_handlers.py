"""The saga steps Inventory performs when order events arrive over RabbitMQ.

Handlers run against the real database; publishing is recorded instead of
sent, so each test asserts both the stock outcome and the event it produced.
"""

import uuid
from decimal import Decimal
from typing import Any

import pytest
from commerce_common.events import EventType
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.events import consumers
from app.models import Product, ReservationStatus, StockReservation

Published = list[tuple[str, dict[str, Any]]]


@pytest.fixture
def published(
    monkeypatch: pytest.MonkeyPatch, session_factory: sessionmaker[Session]
) -> Published:
    events: Published = []

    def record(_url: str, routing_key: str, payload: dict[str, Any], **_: Any) -> None:
        events.append((routing_key, payload))

    monkeypatch.setattr(consumers, "SessionLocal", session_factory)
    monkeypatch.setattr(consumers, "publish_event", record)
    return events


def _product(session_factory: sessionmaker[Session], *, stock: int) -> uuid.UUID:
    with session_factory() as db:
        product = Product(name="Widget", price=Decimal("10.00"), stock_qty=stock)
        db.add(product)
        db.commit()
        return product.id


def _reservations(
    session_factory: sessionmaker[Session], order_id: uuid.UUID
) -> list[StockReservation]:
    with session_factory() as db:
        return list(
            db.scalars(select(StockReservation).where(StockReservation.order_id == order_id))
        )


def _order_created(order_id: uuid.UUID, product_id: uuid.UUID, qty: int) -> dict[str, Any]:
    return {"order_id": str(order_id), "items": [{"product_id": str(product_id), "qty": qty}]}


def test_order_created_holds_stock_and_reports_reserved(
    published: Published, session_factory: sessionmaker[Session]
) -> None:
    product_id = _product(session_factory, stock=5)
    order_id = uuid.uuid4()

    consumers._dispatch(EventType.ORDER_CREATED, _order_created(order_id, product_id, 2))

    [reservation] = _reservations(session_factory, order_id)
    assert reservation.status == ReservationStatus.HELD.value
    assert published == [
        (
            EventType.INVENTORY_RESERVED,
            {"order_id": str(order_id), "reservation_id": str(reservation.id)},
        )
    ]


def test_order_created_without_enough_stock_reports_failed(
    published: Published, session_factory: sessionmaker[Session]
) -> None:
    product_id = _product(session_factory, stock=1)
    order_id = uuid.uuid4()

    consumers._dispatch(EventType.ORDER_CREATED, _order_created(order_id, product_id, 3))

    assert _reservations(session_factory, order_id) == []
    [(routing_key, payload)] = published
    assert routing_key == EventType.INVENTORY_FAILED
    assert payload["order_id"] == str(order_id)
    assert "insufficient stock" in payload["reason"]


def test_order_created_for_an_unknown_product_reports_failed(published: Published) -> None:
    order_id = uuid.uuid4()

    consumers._dispatch(EventType.ORDER_CREATED, _order_created(order_id, uuid.uuid4(), 1))

    [(routing_key, payload)] = published
    assert routing_key == EventType.INVENTORY_FAILED
    assert "product not found" in payload["reason"]


def test_order_paid_commits_and_reports_committed_even_when_redelivered(
    published: Published, session_factory: sessionmaker[Session]
) -> None:
    product_id = _product(session_factory, stock=5)
    order_id = uuid.uuid4()
    consumers._dispatch(EventType.ORDER_CREATED, _order_created(order_id, product_id, 2))
    published.clear()

    consumers._dispatch(EventType.ORDER_PAID, {"order_id": str(order_id)})
    consumers._dispatch(EventType.ORDER_PAID, {"order_id": str(order_id)})

    [reservation] = _reservations(session_factory, order_id)
    assert reservation.status == ReservationStatus.COMMITTED.value
    # The redelivery commits nothing, but the order still needs the signal.
    assert published == [
        (EventType.INVENTORY_COMMITTED, {"order_id": str(order_id), "committed_count": 1}),
        (EventType.INVENTORY_COMMITTED, {"order_id": str(order_id), "committed_count": 0}),
    ]


def test_order_cancelled_releases_the_held_stock(
    published: Published, session_factory: sessionmaker[Session]
) -> None:
    product_id = _product(session_factory, stock=5)
    order_id = uuid.uuid4()
    consumers._dispatch(EventType.ORDER_CREATED, _order_created(order_id, product_id, 2))
    published.clear()

    consumers._dispatch(EventType.ORDER_CANCELLED, {"order_id": str(order_id)})

    [reservation] = _reservations(session_factory, order_id)
    assert reservation.status == ReservationStatus.RELEASED.value
    assert published == []


def test_unknown_events_are_ignored(published: Published) -> None:
    consumers._dispatch("order.renamed", {"order_id": str(uuid.uuid4())})

    assert published == []
