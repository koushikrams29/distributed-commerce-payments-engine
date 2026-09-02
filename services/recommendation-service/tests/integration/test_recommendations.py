import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from commerce_common.auth import Role
from app.services.recommendation_service import RecommendationService
from tests.helpers import auth_header

PRODUCT_A = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
PRODUCT_B = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
PRODUCT_C = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_record_purchase_increments_co_purchase_counts(
    session_factory: sessionmaker[Session],
) -> None:
    order_id = uuid.uuid4()
    db = session_factory()
    try:
        service = RecommendationService(db)
        items = [
            {"product_id": str(PRODUCT_A), "qty": 1},
            {"product_id": str(PRODUCT_B), "qty": 2},
            {"product_id": str(PRODUCT_C), "qty": 1},
        ]
        assert service.record_purchase(order_id=order_id, items=items) is True
        recs = service.get_recommendations(PRODUCT_A)
        product_ids = {item["product_id"] for item in recs}
        assert str(PRODUCT_B) in product_ids
        assert str(PRODUCT_C) in product_ids
    finally:
        db.close()


def test_record_purchase_is_idempotent_per_order(
    session_factory: sessionmaker[Session],
) -> None:
    order_id = uuid.uuid4()
    db = session_factory()
    try:
        service = RecommendationService(db)
        items = [
            {"product_id": str(PRODUCT_A), "qty": 1},
            {"product_id": str(PRODUCT_B), "qty": 1},
        ]
        assert service.record_purchase(order_id=order_id, items=items) is True
        assert service.record_purchase(order_id=order_id, items=items) is False
        recs = service.get_recommendations(PRODUCT_A)
        assert recs[0]["co_purchase_count"] == 1
    finally:
        db.close()


def test_admin_can_read_recommendations(client: TestClient, session_factory) -> None:
    order_id = uuid.uuid4()
    db = session_factory()
    try:
        RecommendationService(db).record_purchase(
            order_id=order_id,
            items=[
                {"product_id": str(PRODUCT_A), "qty": 1},
                {"product_id": str(PRODUCT_B), "qty": 1},
            ],
        )
    finally:
        db.close()

    response = client.get(
        f"/recommendations/{PRODUCT_A}",
        headers=auth_header(role=Role.ADMIN),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["product_id"] == str(PRODUCT_A)
    assert len(body["items"]) == 1
    assert body["items"][0]["product_id"] == str(PRODUCT_B)


def test_shopper_cannot_read_recommendations(client: TestClient) -> None:
    response = client.get(
        f"/recommendations/{PRODUCT_A}",
        headers=auth_header(role=Role.SHOPPER),
    )
    assert response.status_code == 403
