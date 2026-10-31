import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from commerce_common.auth import Role, verify_password
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.models import RefreshToken, User, hash_refresh_token
from app.schemas.auth import TokenPair
from app.services.auth_service import AuthError, AuthService


def test_expired_refresh_token_is_rejected_and_revoked(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as db:
        AuthService(db).ensure_user(
            email="shopper@example.com", password="secret-pass", role=Role.SHOPPER
        )
    raw = client.post(
        "/auth/login",
        data={"username": "shopper@example.com", "password": "secret-pass"},
    ).json()["refresh_token"]
    token_hash = hash_refresh_token(raw)
    with session_factory() as db:
        db.execute(
            update(RefreshToken)
            .where(RefreshToken.token_hash == token_hash)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        db.commit()

    response = client.post("/auth/refresh", json={"refresh_token": raw})

    assert response.status_code == 401
    with session_factory() as db:
        stored = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        assert stored is not None
        assert stored.revoked_at is not None


def test_ensure_user_creates_once_and_keeps_the_first_password(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        created = AuthService(db).ensure_user(
            email="Admin@Example.com", password="first-pass", role=Role.ADMIN
        )
    with session_factory() as db:
        again = AuthService(db).ensure_user(
            email="admin@example.com", password="second-pass", role=Role.SHOPPER
        )

    assert again.id == created.id
    with session_factory() as db:
        users = db.scalars(select(User)).all()
        assert len(users) == 1
        assert users[0].email == "admin@example.com"
        assert users[0].role == Role.ADMIN.value
        assert verify_password("first-pass", users[0].password_hash)


def test_concurrent_refresh_rotates_only_once(
    session_factory: sessionmaker[Session],
) -> None:
    """Two overlapping refreshes must not mint two live descendant tokens."""
    with session_factory() as db:
        AuthService(db).ensure_user(
            email="shopper@example.com", password="secret-pass", role=Role.SHOPPER
        )
        pair = AuthService(db).login("shopper@example.com", "secret-pass")

    barrier = threading.Barrier(2)

    def attempt() -> TokenPair | str:
        db = session_factory()
        try:
            barrier.wait(timeout=10)
            return AuthService(db).refresh(pair.refresh_token)
        except AuthError:
            return "rejected"
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = [future.result() for future in [pool.submit(attempt), pool.submit(attempt)]]

    assert sorted(
        "ok" if isinstance(item, TokenPair) else item for item in outcomes
    ) == ["ok", "rejected"]
    winners = [item for item in outcomes if isinstance(item, TokenPair)]
    assert len(winners) == 1

    with session_factory() as db:
        live = db.scalar(
            select(func.count())
            .select_from(RefreshToken)
            .where(RefreshToken.revoked_at.is_(None))
        )
        # Original revoked + one new live token from the winner.
        assert live == 1
        AuthService(db).refresh(winners[0].refresh_token)
    with session_factory() as db:
        try:
            AuthService(db).refresh(pair.refresh_token)
            raised = False
        except AuthError:
            raised = True
        assert raised
