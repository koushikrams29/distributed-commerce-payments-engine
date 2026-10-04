import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.outbox import OutboxEvent


class OutboxRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, event: OutboxEvent) -> OutboxEvent:
        self.db.add(event)
        self.db.flush()
        return event

    def fetch_unpublished(self, *, limit: int = 50) -> list[OutboxEvent]:
        stmt = (
            select(OutboxEvent)
            .where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_for_aggregate(self, aggregate_id: uuid.UUID) -> list[OutboxEvent]:
        stmt = (
            select(OutboxEvent)
            .where(OutboxEvent.aggregate_id == aggregate_id)
            .order_by(OutboxEvent.created_at.asc(), OutboxEvent.id.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def backlog(self) -> tuple[int, datetime | None]:
        """Rows still waiting for the relay, and when the oldest was written."""
        stmt = select(func.count(), func.min(OutboxEvent.created_at)).where(
            OutboxEvent.published_at.is_(None)
        )
        count, oldest = self.db.execute(stmt).one()
        return count, oldest

    def mark_published(self, event_id: uuid.UUID) -> None:
        event = self.db.get(OutboxEvent, event_id)
        if event is not None:
            event.published_at = datetime.now(UTC)
