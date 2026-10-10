import logging
import threading

from app.core.config import settings
from app.core.db import SessionLocal
from app.events.consumers import _publish_payment_outcome
from app.services.payment_service import PaymentService

logger = logging.getLogger(__name__)


def _reconcile_once() -> int:
    db = SessionLocal()
    try:
        service = PaymentService(db)
        payments = service.reconcile_unresolved()
        for payment in payments:
            _publish_payment_outcome(service, payment)
        return len(payments)
    except Exception:
        db.rollback()
        logger.exception("payment reconciliation failed")
        return 0
    finally:
        db.close()


def start_payment_reconciler(
    *, poll_interval_seconds: float | None = None
) -> threading.Thread:
    interval = poll_interval_seconds or settings.payment_reconcile_poll_interval_seconds

    def _loop() -> None:
        logger.info("payment reconciler started (interval=%ss)", interval)
        while not stopping.wait(interval):
            resolved = _reconcile_once()
            if resolved:
                logger.info("payment reconciler reported %s outcome(s)", resolved)

    stopping = threading.Event()
    thread = threading.Thread(target=_loop, name="payment-reconciler", daemon=True)
    thread.start()
    return thread
