import logging
import threading
import time
from datetime import UTC, datetime

from commerce_common.messaging import publish_event

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.metrics import OUTBOX_PUBLISH_LAG
from app.repositories.outbox_repository import OutboxRepository

logger = logging.getLogger(__name__)


def _relay_once() -> int:
    db = SessionLocal()
    try:
        repository = OutboxRepository(db)
        events = repository.fetch_unpublished()
        for event in events:
            publish_event(
                settings.rabbitmq_url,
                event.event_type,
                event.payload_json,
                trace_context=event.trace_context,
            )
            repository.mark_published(event.id)
            OUTBOX_PUBLISH_LAG.observe(
                max(0.0, (datetime.now(UTC) - event.created_at).total_seconds())
            )
        db.commit()
        return len(events)
    except Exception:
        db.rollback()
        logger.exception("outbox relay failed")
        return 0
    finally:
        db.close()


def start_outbox_relay(*, poll_interval_seconds: float = 1.0) -> threading.Thread:
    def _loop() -> None:
        logger.info("outbox relay started")
        while True:
            published = _relay_once()
            if published:
                logger.info("relayed %s outbox event(s)", published)
            time.sleep(poll_interval_seconds)

    thread = threading.Thread(target=_loop, name="outbox-relay", daemon=True)
    thread.start()
    return thread
