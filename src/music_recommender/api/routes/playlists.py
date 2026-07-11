from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, status

from music_recommender.api.dependencies import (
    get_api_service,
    get_playlist_export_service,
    require_approved_mutating_user,
)
from music_recommender.api.models import (
    PlaylistCreateRequest,
    ProductPlaylistExportRequest,
)
from music_recommender.auth.models import ProductUser
from music_recommender.models import JsonDict
from music_recommender.product.playlist_export_service import PlaylistExportService

router = APIRouter(tags=["playlists"])
product_router = APIRouter(tags=["playlists"])


@router.post("/playlists")
def create_playlist(
    request: PlaylistCreateRequest,
    service: Annotated[Any, Depends(get_api_service)],
) -> Any:
    return service.create_playlist(request)


@product_router.post(
    "/me/recommendations/{session_id}/playlist",
    status_code=status.HTTP_201_CREATED,
)
def export_reviewed_playlist(
    session_id: UUID,
    request: ProductPlaylistExportRequest,
    response: Response,
    user: Annotated[ProductUser, Depends(require_approved_mutating_user)],
    service: Annotated[PlaylistExportService, Depends(get_playlist_export_service)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
) -> JsonDict:
    result = service.export(
        account_id=user.account_id,
        session_id=str(session_id),
        name=request.name,
        description=request.description,
        public=request.public,
        recording_mbids=tuple(str(mbid) for mbid in request.recording_mbids),
        idempotency_key=idempotency_key,
    )
    if result.idempotent_replay:
        response.status_code = status.HTTP_200_OK
    return result.to_dict()
