from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status

from music_recommender.api.dependencies import (
    get_api_service,
    get_feedback_evaluation_service,
    require_approved_mutating_user,
    require_approved_user,
)
from music_recommender.api.models import FeedbackRequest, ProductFeedbackRequest
from music_recommender.auth.models import ProductUser
from music_recommender.models import JsonDict
from music_recommender.product.feedback_service import FeedbackEvaluationService

router = APIRouter(tags=["feedback"])
product_router = APIRouter(tags=["feedback"])


@product_router.get("/me/preferences")
def get_product_preferences(
    user: Annotated[ProductUser, Depends(require_approved_user)],
    service: Annotated[
        FeedbackEvaluationService,
        Depends(get_feedback_evaluation_service),
    ],
) -> JsonDict:
    return service.get_preferences(account_id=user.account_id)


@product_router.delete("/me/preferences/artists/{artist_mbid}")
def unblock_product_artist(
    artist_mbid: UUID,
    user: Annotated[ProductUser, Depends(require_approved_mutating_user)],
    service: Annotated[
        FeedbackEvaluationService,
        Depends(get_feedback_evaluation_service),
    ],
) -> JsonDict:
    return service.unblock_artist(
        account_id=user.account_id,
        artist_mbid=str(artist_mbid),
    )


@router.post("/feedback")
def record_feedback(
    request: FeedbackRequest,
    service: Annotated[Any, Depends(get_api_service)],
) -> Any:
    return service.record_feedback(request)


@product_router.post(
    "/me/recommendations/{session_id}/feedback",
    status_code=status.HTTP_201_CREATED,
)
def record_product_feedback(
    session_id: UUID,
    request: ProductFeedbackRequest,
    user: Annotated[ProductUser, Depends(require_approved_mutating_user)],
    service: Annotated[
        FeedbackEvaluationService,
        Depends(get_feedback_evaluation_service),
    ],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
) -> JsonDict:
    return service.record_feedback(
        account_id=user.account_id,
        session_id=str(session_id),
        recording_mbid=str(request.recording_mbid),
        event_type=request.event_type,
        reason=request.reason,
        idempotency_key=idempotency_key,
    ).to_dict()
