from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from music_recommender.api.dependencies import get_api_service
from music_recommender.api.models import PlaylistCreateRequest

router = APIRouter(tags=["playlists"])


@router.post("/playlists")
def create_playlist(
    request: PlaylistCreateRequest,
    service: Annotated[Any, Depends(get_api_service)],
) -> Any:
    return service.create_playlist(request)
