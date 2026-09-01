import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Notification


class NotificationRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, notification: Notification) -> Notification:
        self.db.add(notification)
        self.db.flush()
        return notification

    def get_for_order_and_channel(
        self, *, order_id: uuid.UUID, channel: str
    ) -> Notification | None:
        stmt = select(Notification).where(
            Notification.order_id == order_id,
            Notification.channel == channel,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_for_order(self, order_id: uuid.UUID) -> list[Notification]:
        stmt = (
            select(Notification)
            .where(Notification.order_id == order_id)
            .order_by(Notification.sent_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())
