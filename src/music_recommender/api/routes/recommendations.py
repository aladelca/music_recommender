from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from music_recommender.api.dependencies import (
    get_api_service,
    get_recommendation_service,
    require_approved_mutating_user,
    require_approved_user,
)
from music_recommender.api.models import (
    ProductRecommendationRequest,
    RecommendationRequest,
    ReviewRecommendationRequest,
)
from music_recommender.auth.models import ProductUser
from music_recommender.models import JsonDict
from music_recommender.observability import (
    RecommendationCoverageObservation,
    mark_recommendation_coverage,
)
from music_recommender.product.recommendation_service import (
    RecommendationService,
    recommendation_bundle_payload,
    recommendation_history_payload,
)

router = APIRouter(tags=["recommendations"])
product_router = APIRouter(tags=["recommendations"])


@router.post("/recommendations")
def recommend(
    request: RecommendationRequest,
    service: Annotated[Any, Depends(get_api_service)],
) -> Any:
    return service.recommend(request)


@product_router.post("/me/recommendations", status_code=status.HTTP_201_CREATED)
def generate_product_recommendations(
    request: ProductRecommendationRequest,
    http_request: Request,
    user: Annotated[ProductUser, Depends(require_approved_mutating_user)],
    service: Annotated[RecommendationService, Depends(get_recommendation_service)],
) -> JsonDict:
    bundle = service.generate(
        account_id=user.account_id,
        prompt=request.prompt,
        adventure=request.adventure,
        allow_explicit=request.allow_explicit,
        seed_ids=tuple(str(seed_id) for seed_id in request.seed_ids),
    )
    _mark_generated_coverage(http_request, bundle.session.source_snapshot)
    return recommendation_bundle_payload(bundle)


@product_router.get("/me/recommendations")
def list_product_recommendations(
    user: Annotated[ProductUser, Depends(require_approved_user)],
    service: Annotated[RecommendationService, Depends(get_recommendation_service)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: Annotated[str | None, Query(min_length=1, max_length=512)] = None,
) -> JsonDict:
    return recommendation_history_payload(
        service.history(account_id=user.account_id, limit=limit, cursor=cursor)
    )


@product_router.get("/me/recommendations/{session_id}")
def get_product_recommendation(
    session_id: UUID,
    user: Annotated[ProductUser, Depends(require_approved_user)],
    service: Annotated[RecommendationService, Depends(get_recommendation_service)],
) -> JsonDict:
    return recommendation_bundle_payload(
        service.get(account_id=user.account_id, session_id=str(session_id))
    )


@product_router.put("/me/recommendations/{session_id}/selection")
def review_product_recommendation(
    session_id: UUID,
    request: ReviewRecommendationRequest,
    user: Annotated[ProductUser, Depends(require_approved_mutating_user)],
    service: Annotated[RecommendationService, Depends(get_recommendation_service)],
) -> JsonDict:
    return recommendation_bundle_payload(
        service.review(
            account_id=user.account_id,
            session_id=str(session_id),
            recording_mbids=tuple(str(mbid) for mbid in request.recording_mbids),
            playlist_name=request.playlist_name,
            playlist_public=request.public,
        )
    )


def _mark_generated_coverage(request: Request, source_snapshot: dict[str, Any]) -> None:
    coverage = source_snapshot.get("coverage")
    if not isinstance(coverage, dict):
        return
    status_value = coverage.get("status")
    if status_value not in {"ready", "degraded", "insufficient"}:
        return
    try:
        observation = RecommendationCoverageObservation(
            status=status_value,
            candidate_count=int(coverage["candidate_count"]),
            mapped_count=int(coverage["mapped_count"]),
            evidence_count=int(coverage["evidence_count"]),
            evidence_coverage=float(coverage["evidence_coverage"]),
        )
    except (KeyError, TypeError, ValueError):
        return
    mark_recommendation_coverage(request, observation)
