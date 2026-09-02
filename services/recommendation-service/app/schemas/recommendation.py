import uuid

from pydantic import BaseModel, Field


class RecommendationItem(BaseModel):
    product_id: uuid.UUID
    co_purchase_count: int


class RecommendationResponse(BaseModel):
    product_id: uuid.UUID
    items: list[RecommendationItem]
