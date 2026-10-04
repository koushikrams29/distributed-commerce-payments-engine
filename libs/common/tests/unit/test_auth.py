from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from commerce_common.auth import (
    Role,
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

SECRET = "unit-test-secret-at-least-32-chars!!"


def _signed(**claims: object) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(uuid4()),
        "role": Role.SHOPPER.value,
        "typ": "access",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        **claims,
    }
    return jwt.encode(payload, SECRET, algorithm="HS256")


def test_password_round_trip() -> None:
    hashed = hash_password("correct-horse")
    assert verify_password("correct-horse", hashed)
    assert not verify_password("wrong-password", hashed)


def test_password_hashes_are_salted() -> None:
    assert hash_password("correct-horse") != hash_password("correct-horse")


def test_passwords_beyond_bcrypt_limit_are_refused_not_truncated() -> None:
    hashed = hash_password("a" * 72)

    # bcrypt ignores bytes past 72, so accepting a longer password would let
    # "a" * 72 + anything log in as this user.
    assert not verify_password("a" * 73, hashed)
    with pytest.raises(ValueError, match="72 bytes"):
        hash_password("a" * 73)


def test_access_token_round_trip() -> None:
    user_id = uuid4()
    token = create_access_token(
        secret=SECRET,
        user_id=user_id,
        role=Role.ADMIN,
        expires_minutes=5,
    )
    payload = decode_access_token(secret=SECRET, token=token)
    assert payload.user_id == user_id
    assert payload.role == Role.ADMIN
    assert payload.expires_at is not None


def test_forged_token_is_rejected() -> None:
    token = create_access_token(
        secret=SECRET,
        user_id=uuid4(),
        role=Role.SHOPPER,
        expires_minutes=5,
    )
    with pytest.raises(TokenError):
        decode_access_token(secret="a-different-secret-32-characters!!", token=token)


def test_expired_token_is_rejected() -> None:
    token = create_access_token(
        secret=SECRET,
        user_id=uuid4(),
        role=Role.SHOPPER,
        expires_minutes=-1,
    )
    with pytest.raises(TokenError):
        decode_access_token(secret=SECRET, token=token)


@pytest.mark.parametrize("typ", ["refresh", None])
def test_only_access_tokens_are_accepted(typ: str | None) -> None:
    with pytest.raises(TokenError, match="not an access token"):
        decode_access_token(secret=SECRET, token=_signed(typ=typ))


@pytest.mark.parametrize(
    "claims",
    [
        {"sub": "not-a-uuid"},
        {"role": "superuser"},
        {"role": None},
    ],
    ids=["bad-subject", "unknown-role", "missing-role"],
)
def test_malformed_claims_are_rejected(claims: dict[str, object]) -> None:
    with pytest.raises(TokenError, match="malformed"):
        decode_access_token(secret=SECRET, token=_signed(**claims))
