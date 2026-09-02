import uuid

from commerce_common.auth import Role, create_access_token

from app.core.config import settings


def auth_header(*, role: Role = Role.ADMIN) -> dict[str, str]:
    token = create_access_token(
        secret=settings.jwt_secret,
        user_id=uuid.uuid4(),
        role=role,
        expires_minutes=15,
    )
    return {"Authorization": f"Bearer {token}"}
