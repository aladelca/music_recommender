from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from music_recommender.models import JsonDict
from music_recommender.storage.protocols import (
    AccessStatus,
    ApplicationSessionRecord,
)


@dataclass(frozen=True)
class OAuthAuthorizationRequest:
    authorization_url: str = field(repr=False)
    state: str = field(repr=False)
    return_path: str
    expires_at: datetime


@dataclass(frozen=True)
class ConsumedOAuthState:
    code_verifier: str = field(repr=False)
    return_path: str


@dataclass(frozen=True)
class SessionCredentials:
    session_token: str = field(repr=False)
    csrf_token: str = field(repr=False)
    record: ApplicationSessionRecord
    max_age_seconds: int


@dataclass(frozen=True)
class ProductUser:
    account_id: str
    display_name: str | None
    access_status: AccessStatus
    seed_ready: bool
    reauthorization_required: bool

    def to_dict(self) -> JsonDict:
        return {
            "account_id": self.account_id,
            "display_name": self.display_name,
            "access_status": self.access_status,
            "seed_ready": self.seed_ready,
            "reauthorization_required": self.reauthorization_required,
        }


@dataclass(frozen=True)
class OAuthLoginResult:
    user: ProductUser
    credentials: SessionCredentials
    return_path: str
