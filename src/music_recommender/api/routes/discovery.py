from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, status

from music_recommender.api.dependencies import (
    get_discovery_job_service,
    require_approved_mutating_user,
    require_approved_user,
)
from music_recommender.auth.models import ProductUser
from music_recommender.models import JsonDict
from music_recommender.product.discovery_service import (
    DiscoveryJobNotFoundError,
    DiscoveryJobService,
    discovery_job_payload,
)

router = APIRouter(prefix="/discovery", tags=["music discovery"])


@router.post("/jobs", status_code=status.HTTP_202_ACCEPTED)
def enqueue_discovery_job(
    user: Annotated[ProductUser, Depends(require_approved_mutating_user)],
    service: Annotated[DiscoveryJobService, Depends(get_discovery_job_service)],
) -> JsonDict:
    job = service.enqueue(account_id=user.account_id)
    return discovery_job_payload(job)


@router.get("/jobs/{job_id}")
def get_discovery_job(
    user: Annotated[ProductUser, Depends(require_approved_user)],
    service: Annotated[DiscoveryJobService, Depends(get_discovery_job_service)],
    job_id: Annotated[str, Path(min_length=1, max_length=100)],
) -> JsonDict:
    job = service.get(account_id=user.account_id, job_id=job_id)
    if job is None:
        raise DiscoveryJobNotFoundError("Discovery job was not found.")
    return discovery_job_payload(job)
