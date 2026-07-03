from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from music_recommender.api.dependencies import get_api_service
from music_recommender.api.models import ProfileSyncRequest

router = APIRouter(tags=["profile"])


@router.post("/profile/sync")
def sync_profile(
    request: ProfileSyncRequest,
    service: Annotated[Any, Depends(get_api_service)],
) -> Any:
    return service.sync_profile(request)


@router.get("/profile")
def get_profile_status(service: Annotated[Any, Depends(get_api_service)]) -> Any:
    return service.get_profile_status()
