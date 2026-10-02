import logging
import threading
import time

from app.core.config import settings
from app.core.db import SessionLocal
from app.services.order_service import OrderService

logger = logging.getLogger(__name__)


def _reconcile_once() -> int:
    db = SessionLocal()
    try:
        return OrderService(db).reconcile_stuck_orders()
    except Exception:
        logger.exception("order reconciliation failed")
        return 0
    finally:
        db.close()


def start_order_reconciler(
    *, poll_interval_seconds: float | None = None
) -> threading.Thread:
    interval = poll_interval_seconds or settings.reconcile_poll_interval_seconds

    def _loop() -> None:
        logger.info("order reconciler started (interval=%ss)", interval)
        while True:
            cancelled = _reconcile_once()
            if cancelled:
                logger.info("reconciler cancelled %s stuck order(s)", cancelled)
            time.sleep(interval)

    thread = threading.Thread(target=_loop, name="order-reconciler", daemon=True)
    thread.start()
    return thread
