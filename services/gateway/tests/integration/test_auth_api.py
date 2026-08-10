from commerce_common.auth import Role, hash_password
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models import User


def _create_user(
    session_factory: sessionmaker[Session],
    *,
    email: str,
    password: str,
    role: Role = Role.SHOPPER,
) -> None:
    db = session_factory()
    try:
        db.add(
            User(
                email=email.lower(),
                password_hash=hash_password(password),
                role=role.value,
            )
        )
        db.commit()
    finally:
        db.close()


def test_login_returns_token_pair(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _create_user(session_factory, email="shopper@example.com", password="secret-pass")

    response = client.post(
        "/auth/login",
        data={"username": "shopper@example.com", "password": "secret-pass"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]


def test_login_rejects_bad_password(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _create_user(session_factory, email="shopper@example.com", password="secret-pass")

    response = client.post(
        "/auth/login",
        data={"username": "shopper@example.com", "password": "wrong"},
    )

    assert response.status_code == 401


def test_login_rejects_unknown_email(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        data={"username": "nobody@example.com", "password": "whatever"},
    )

    assert response.status_code == 401


def test_refresh_rotates_and_returns_new_tokens(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _create_user(session_factory, email="shopper@example.com", password="secret-pass")
    login = client.post(
        "/auth/login",
        data={"username": "shopper@example.com", "password": "secret-pass"},
    ).json()

    first_refresh = login["refresh_token"]
    refreshed = client.post("/auth/refresh", json={"refresh_token": first_refresh})

    assert refreshed.status_code == 200
    new_pair = refreshed.json()
    assert new_pair["access_token"] != login["access_token"]
    assert new_pair["refresh_token"] != first_refresh

    # Old refresh token must be dead after rotation.
    replay = client.post("/auth/refresh", json={"refresh_token": first_refresh})
    assert replay.status_code == 401


def test_refresh_rejects_garbage_token(client: TestClient) -> None:
    response = client.post(
        "/auth/refresh",
        json={"refresh_token": "this-is-not-a-real-refresh-token"},
    )
    assert response.status_code == 401
