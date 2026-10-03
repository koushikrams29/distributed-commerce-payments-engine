import logging
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.metrics import NOTIFICATIONS_SENT
from app.models import Notification, NotificationChannel, NotificationStatus
from app.repositories.notification_repository import NotificationRepository

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, db: Session):
        self.db = db
        self.repository = NotificationRepository(db)

    def send_order_confirmation(
        self,
        *,
        order_id: uuid.UUID,
        channel: str | None = None,
    ) -> tuple[Notification, bool]:
        """Record a fake confirmation once the order is fulfilled (FR-8).

        Idempotent per (order_id, channel) — replays return the existing row.
        """
        channel = channel or settings.default_channel
        existing = self.repository.get_for_order_and_channel(
            order_id=order_id, channel=channel
        )
        if existing is not None:
            return existing, False

        notification = Notification(
            order_id=order_id,
            channel=channel,
            status=NotificationStatus.SENT.value,
        )

        try:
            self.repository.add(notification)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self.repository.get_for_order_and_channel(
                order_id=order_id, channel=channel
            )
            if existing is None:
                raise
            return existing, False

        NOTIFICATIONS_SENT.labels(channel).inc()
        self.db.refresh(notification)
        logger.info(
            "fake %s confirmation sent for order=%s notification=%s",
            channel,
            order_id,
            notification.id,
        )
        return notification, True

    def list_for_order(self, order_id: uuid.UUID) -> list[Notification]:
        return self.repository.list_for_order(order_id)
