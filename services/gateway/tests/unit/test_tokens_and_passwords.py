from uuid import uuid4

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


def test_password_round_trip() -> None:
    hashed = hash_password("correct-horse")
    assert verify_password("correct-horse", hashed)
    assert not verify_password("wrong-password", hashed)


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
