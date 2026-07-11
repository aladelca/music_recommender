from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from music_recommender.api.dependencies import (
    get_seed_service,
    require_approved_mutating_user,
    require_approved_user,
)
from music_recommender.api.models import ReplaceSeedsRequest
from music_recommender.auth.models import ProductUser
from music_recommender.models import JsonDict
from music_recommender.product.seed_service import (
    SeedSelection,
    SeedService,
    seed_record_payload,
)
from music_recommender.storage.protocols import MusicEntityType

router = APIRouter(tags=["music discovery"])


@router.get("/music/search")
def search_music(
    user: Annotated[ProductUser, Depends(require_approved_user)],
    service: Annotated[SeedService, Depends(get_seed_service)],
    q: Annotated[str, Query(min_length=2, max_length=100)],
    entity_type: Annotated[
        MusicEntityType,
        Query(alias="type", pattern="^(artist|recording)$"),
    ],
) -> JsonDict:
    del user
    return service.search(query=q, entity_type=entity_type).to_dict()


@router.put("/me/seeds")
def replace_seeds(
    request: ReplaceSeedsRequest,
    user: Annotated[ProductUser, Depends(require_approved_mutating_user)],
    service: Annotated[SeedService, Depends(get_seed_service)],
) -> JsonDict:
    records = service.replace(
        account_id=user.account_id,
        selections=tuple(
            SeedSelection(
                entity_type=seed.entity_type,
                mbid=str(seed.mbid),
            )
            for seed in request.seeds
        ),
    )
    return {"seeds": [seed_record_payload(seed) for seed in records]}


@router.get("/me/seeds")
def list_seeds(
    user: Annotated[ProductUser, Depends(require_approved_user)],
    service: Annotated[SeedService, Depends(get_seed_service)],
) -> JsonDict:
    records = service.list(account_id=user.account_id)
    return {"seeds": [seed_record_payload(seed) for seed in records]}
