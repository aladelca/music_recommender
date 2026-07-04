from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from music_recommender.api.dependencies import get_api_service
from music_recommender.api.models import FeedbackRequest

router = APIRouter(tags=["feedback"])


@router.post("/feedback")
def record_feedback(
    request: FeedbackRequest,
    service: Annotated[Any, Depends(get_api_service)],
) -> Any:
    return service.record_feedback(request)
