from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from music_recommender.api.dependencies import (
    get_feedback_evaluation_service,
    require_approved_mutating_user,
    require_approved_user,
)
from music_recommender.api.models import SessionEvaluationRequest
from music_recommender.auth.models import ProductUser
from music_recommender.models import JsonDict
from music_recommender.product.feedback_service import (
    FeedbackEvaluationService,
    evaluation_payload,
)

router = APIRouter(tags=["evaluations"])


@router.put("/me/recommendations/{session_id}/evaluation")
def save_session_evaluation(
    session_id: UUID,
    request: SessionEvaluationRequest,
    user: Annotated[ProductUser, Depends(require_approved_mutating_user)],
    service: Annotated[
        FeedbackEvaluationService,
        Depends(get_feedback_evaluation_service),
    ],
) -> JsonDict:
    return evaluation_payload(
        service.save_evaluation(
            account_id=user.account_id,
            session_id=str(session_id),
            comparison=request.comparison,
            explanation_usefulness=request.explanation_usefulness,
            novelty_quality=request.novelty_quality,
            comment=request.comment,
        )
    )


@router.get("/me/recommendations/{session_id}/evaluation")
def get_session_evaluation(
    session_id: UUID,
    user: Annotated[ProductUser, Depends(require_approved_user)],
    service: Annotated[
        FeedbackEvaluationService,
        Depends(get_feedback_evaluation_service),
    ],
) -> JsonDict:
    return evaluation_payload(
        service.get_evaluation(
            account_id=user.account_id,
            session_id=str(session_id),
        )
    )
