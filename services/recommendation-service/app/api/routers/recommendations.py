import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from commerce_common.auth import AccessTokenPayload, Role

from app.core.db import get_db
from app.core.security import require_roles
from app.schemas.recommendation import RecommendationItem, RecommendationResponse
from app.services.recommendation_service import RecommendationService

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("/{product_id}", response_model=RecommendationResponse)
def get_recommendations(
    product_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: AccessTokenPayload = Depends(require_roles(Role.ADMIN)),
    limit: int = Query(default=5, ge=1, le=20),
):
    items = RecommendationService(db).get_recommendations(product_id, limit=limit)
    return RecommendationResponse(
        product_id=product_id,
        items=[RecommendationItem(**item) for item in items],
    )
