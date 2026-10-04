import uuid

import pytest
from commerce_common.events import EventType

from app.events import consumers, reconciler


class FakeSession:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class RecordingOrderService:
    calls: list[tuple[str, uuid.UUID]] = []

    def __init__(self, db: FakeSession) -> None:
        self.db = db

    def __getattr__(self, name: str):
        def handler(order_id: uuid.UUID) -> None:
            RecordingOrderService.calls.append((name, order_id))

        return handler


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> FakeSession:
    fake = FakeSession()
    RecordingOrderService.calls = []
    monkeypatch.setattr(consumers, "SessionLocal", lambda: fake)
    monkeypatch.setattr(consumers, "OrderService", RecordingOrderService)
    return fake


@pytest.mark.parametrize(
    ("routing_key", "handler"),
    [
        (EventType.INVENTORY_RESERVED, "on_inventory_reserved"),
        (EventType.INVENTORY_FAILED, "on_inventory_failed"),
        (EventType.PAYMENT_SUCCEEDED, "on_payment_succeeded"),
        (EventType.PAYMENT_FAILED, "on_payment_failed"),
        (EventType.INVENTORY_COMMITTED, "on_inventory_committed"),
    ],
)
def test_each_saga_event_reaches_its_handler(
    session: FakeSession, routing_key: str, handler: str
) -> None:
    order_id = uuid.uuid4()

    consumers._dispatch(routing_key, {"order_id": str(order_id)})

    assert RecordingOrderService.calls == [(handler, order_id)]
    assert session.closed


def test_unknown_events_are_logged_and_ignored(
    session: FakeSession, caplog: pytest.LogCaptureFixture
) -> None:
    consumers._dispatch("order.renamed", {"order_id": str(uuid.uuid4())})

    assert RecordingOrderService.calls == []
    assert "order.renamed" in caplog.text
    assert session.closed


def test_session_is_closed_when_a_handler_fails(
    session: FakeSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(self: RecordingOrderService, order_id: uuid.UUID) -> None:
        raise RuntimeError("database went away")

    monkeypatch.setattr(RecordingOrderService, "on_payment_failed", explode, raising=False)

    with pytest.raises(RuntimeError):
        consumers._dispatch(EventType.PAYMENT_FAILED, {"order_id": str(uuid.uuid4())})

    assert session.closed


def test_a_failed_reconciliation_pass_does_not_stop_the_reconciler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeSession()

    class FailingOrderService:
        def __init__(self, db: FakeSession) -> None:
            pass

        def reconcile_stuck_orders(self) -> int:
            raise RuntimeError("database went away")

    monkeypatch.setattr(reconciler, "SessionLocal", lambda: fake)
    monkeypatch.setattr(reconciler, "OrderService", FailingOrderService)

    # The loop calls this every interval; raising would kill the thread for good.
    assert reconciler._reconcile_once() == 0
    assert fake.closed
