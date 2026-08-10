import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RefreshToken, User, hash_refresh_token


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email.lower())
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        stmt = select(User).where(User.id == user_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def add(self, user: User) -> User:
        self.db.add(user)
        self.db.flush()
        return user


class RefreshTokenRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, token: RefreshToken) -> RefreshToken:
        self.db.add(token)
        self.db.flush()
        return token

    def get_valid_by_raw_token(self, raw_token: str) -> RefreshToken | None:
        token_hash = hash_refresh_token(raw_token)
        stmt = select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
        )
        return self.db.execute(stmt).scalar_one_or_none()
