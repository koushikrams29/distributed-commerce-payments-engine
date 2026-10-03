from typing import Any

from prometheus_client import Counter, Histogram
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session, UOWTransaction

from app.models.order import Order, OrderStatus

ORDER_STATUS_TRANSITIONS = Counter(
    "order_status_transitions_total",
    "Committed order status changes. from_status is 'none' when the order is created.",
    ["from_status", "to_status"],
)
OUTBOX_PUBLISH_LAG = Histogram(
    "outbox_publish_lag_seconds",
    "Delay between an outbox row being written and the relay publishing it.",
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 300.0),
)
RECONCILER_ACTIONS = Counter(
    "order_reconciler_actions_total",
    "Stuck orders the reconciler cancelled or re-drove.",
)

_PENDING_KEY = "order_status_transitions"


# Status is written from event handlers, the reconciler and the HTTP fallback.
# Counting at the session level catches every path, and only after commit, so
# a rolled-back transition is never reported.
@event.listens_for(Session, "before_flush")
def _collect_transitions(session: Session, _context: UOWTransaction, _instances: Any) -> None:
    pending: list[tuple[str, str]] = session.info.setdefault(_PENDING_KEY, [])
    for obj in session.new:
        if isinstance(obj, Order):
            pending.append(("none", obj.status or OrderStatus.PENDING.value))
    for obj in session.dirty:
        if isinstance(obj, Order):
            history = inspect(obj).attrs.status.history
            if history.added:
                previous = history.deleted[0] if history.deleted else "unknown"
                if previous != history.added[0]:
                    pending.append((previous, history.added[0]))


@event.listens_for(Session, "after_commit")
def _record_transitions(session: Session) -> None:
    for previous, current in session.info.pop(_PENDING_KEY, []):
        ORDER_STATUS_TRANSITIONS.labels(previous, current).inc()


@event.listens_for(Session, "after_rollback")
def _discard_transitions(session: Session) -> None:
    session.info.pop(_PENDING_KEY, None)
