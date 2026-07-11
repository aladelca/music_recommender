from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from music_recommender.models import JsonDict
from music_recommender.storage.protocols import (
    BetaAccessRepository,
    BetaAccountRecord,
)


class BetaAccessService:
    APPROVED_LIMIT = 5

    def __init__(
        self,
        *,
        repository: BetaAccessRepository,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.now = now or (lambda: datetime.now(UTC))

    def pending(self) -> tuple[BetaAccountRecord, ...]:
        return self.repository.list_pending()

    def approve(self, account_id: str) -> BetaAccountRecord:
        return self.repository.approve(
            account_id=_account_id(account_id),
            changed_at=_aware_utc(self.now()),
        )

    def revoke(self, account_id: str) -> BetaAccountRecord:
        return self.repository.revoke(
            account_id=_account_id(account_id),
            changed_at=_aware_utc(self.now()),
        )

    def status(self, account_id: str | None = None) -> JsonDict:
        payload: JsonDict = {
            "approved_count": self.repository.approved_count(),
            "approved_limit": self.APPROVED_LIMIT,
        }
        if account_id is not None:
            account = self.repository.get(account_id=_account_id(account_id))
            if account is None:
                raise LookupError("Account not found.")
            payload["account"] = _safe_account(account)
        return payload


def safe_account_payload(account: BetaAccountRecord) -> JsonDict:
    return _safe_account(account)


def _safe_account(account: BetaAccountRecord) -> JsonDict:
    return {
        "account_id": account.account_id,
        "access_status": account.access_status,
    }


def _account_id(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 255:
        raise ValueError("account_id must contain between 1 and 255 characters.")
    return normalized


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Beta administration timestamps must be timezone-aware.")
    return value.astimezone(UTC)
