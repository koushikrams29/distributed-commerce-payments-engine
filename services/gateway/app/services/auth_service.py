import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from commerce_common.auth import Role, create_access_token, hash_password, verify_password

from app.core.config import settings
from app.models import RefreshToken, User, hash_refresh_token, new_refresh_token
from app.repositories.auth_repository import RefreshTokenRepository, UserRepository
from app.schemas.auth import TokenPair


class AuthError(Exception):
    """Invalid credentials or refresh token."""


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.users = UserRepository(db)
        self.refresh_tokens = RefreshTokenRepository(db)

    def login(self, email: str, password: str) -> TokenPair:
        user = self.users.get_by_email(email)
        if user is None or not verify_password(password, user.password_hash):
            # Same error either way so attackers cannot probe which emails exist.
            raise AuthError("invalid email or password")
        return self._issue_token_pair(user)

    def refresh(self, raw_refresh_token: str) -> TokenPair:
        stored = self.refresh_tokens.get_valid_by_raw_token(raw_refresh_token)
        if stored is None:
            raise AuthError("invalid refresh token")

        now = datetime.now(UTC)
        if stored.expires_at <= now:
            stored.revoked_at = now
            self.db.commit()
            raise AuthError("invalid refresh token")

        # Rotation: this token can never be used again.
        stored.revoked_at = now
        user = self.users.get_by_id(stored.user_id)
        if user is None:
            self.db.commit()
            raise AuthError("invalid refresh token")

        return self._issue_token_pair(user)

    def ensure_user(
        self, *, email: str, password: str, role: Role
    ) -> User:
        """Create a user if missing — used for local/dev seed accounts."""
        existing = self.users.get_by_email(email)
        if existing is not None:
            return existing
        user = User(
            email=email.lower(),
            password_hash=hash_password(password),
            role=role.value,
        )
        self.users.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def _issue_token_pair(self, user: User) -> TokenPair:
        access = create_access_token(
            secret=settings.jwt_secret,
            user_id=user.id,
            role=Role(user.role),
            expires_minutes=settings.access_token_expire_minutes,
        )
        raw_refresh = new_refresh_token()
        self.refresh_tokens.add(
            RefreshToken(
                user_id=user.id,
                token_hash=hash_refresh_token(raw_refresh),
                expires_at=datetime.now(UTC)
                + timedelta(days=settings.refresh_token_expire_days),
            )
        )
        self.db.commit()
        return TokenPair(access_token=access, refresh_token=raw_refresh)
