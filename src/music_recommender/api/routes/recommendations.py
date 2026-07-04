from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from music_recommender.api.dependencies import get_api_service
from music_recommender.api.models import RecommendationRequest

router = APIRouter(tags=["recommendations"])


@router.post("/recommendations")
def recommend(
    request: RecommendationRequest,
    service: Annotated[Any, Depends(get_api_service)],
) -> Any:
    return service.recommend(request)
