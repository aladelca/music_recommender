from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from music_recommender.auth.beta_access import BetaAccessService
from music_recommender.beta_admin_cli import main
from music_recommender.storage.protocols import (
    ApprovedUserLimitError,
    BetaAccountRecord,
    EvaluationCompletenessRecord,
)


class InMemoryBetaAccessRepository:
    def __init__(self) -> None:
        now = datetime(2030, 1, 1, tzinfo=UTC)
        self.records = {
            f"account-{index}": BetaAccountRecord(
                account_id=f"account-{index}",
                access_status="pending",
                last_login_at=now,
            )
            for index in range(1, 7)
        }

    def list_pending(self) -> tuple[BetaAccountRecord, ...]:
        return tuple(
            record for record in self.records.values() if record.access_status == "pending"
        )

    def get(self, *, account_id: str) -> BetaAccountRecord | None:
        return self.records.get(account_id)

    def approved_count(self) -> int:
        return sum(record.access_status == "approved" for record in self.records.values())

    def approve(self, *, account_id: str, changed_at: datetime) -> BetaAccountRecord:
        del changed_at
        record = self.records.get(account_id)
        if record is None:
            raise LookupError("Account not found.")
        if record.access_status != "approved" and self.approved_count() >= 5:
            raise ApprovedUserLimitError("Outside the Loop beta permits at most five users.")
        updated = BetaAccountRecord(
            account_id=record.account_id,
            access_status="approved",
            last_login_at=record.last_login_at,
        )
        self.records[account_id] = updated
        return updated

    def revoke(self, *, account_id: str, changed_at: datetime) -> BetaAccountRecord:
        del changed_at
        record = self.records.get(account_id)
        if record is None:
            raise LookupError("Account not found.")
        updated = BetaAccountRecord(
            account_id=record.account_id,
            access_status="revoked",
            last_login_at=record.last_login_at,
        )
        self.records[account_id] = updated
        return updated


def test_beta_access_service_enforces_five_approved_users() -> None:
    service = build_service()

    for index in range(1, 6):
        approved = service.approve(f"account-{index}")
        assert approved.access_status == "approved"

    with pytest.raises(ApprovedUserLimitError, match="at most five"):
        service.approve("account-6")

    assert service.status()["approved_count"] == 5
    assert service.status()["approved_limit"] == 5


def test_beta_admin_cli_prints_only_safe_account_status_data(
    capsys: pytest.CaptureFixture[str],
) -> None:
    service = build_service()

    assert main(["approve", "account-1"], service=service) == 0
    approved = json.loads(capsys.readouterr().out)
    assert approved == {"account_id": "account-1", "access_status": "approved"}

    assert main(["pending"], service=service) == 0
    pending = json.loads(capsys.readouterr().out)
    assert all(set(item) == {"account_id", "access_status"} for item in pending["accounts"])
    assert "ciphertext" not in json.dumps(pending)
    assert "token" not in json.dumps(pending)

    assert main(["revoke", "account-1"], service=service) == 0
    revoked = json.loads(capsys.readouterr().out)
    assert revoked == {"account_id": "account-1", "access_status": "revoked"}


def test_beta_admin_status_can_report_one_account_without_profile_data(
    capsys: pytest.CaptureFixture[str],
) -> None:
    service = build_service()

    assert main(["status", "account-2"], service=service) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "account": {"account_id": "account-2", "access_status": "pending"},
        "approved_count": 0,
        "approved_limit": 5,
    }


def test_beta_admin_reports_only_aggregate_evaluation_completion(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class EvaluationReader:
        def completeness(self) -> EvaluationCompletenessRecord:
            return EvaluationCompletenessRecord(
                approved_accounts=5,
                eligible_sessions=12,
                completed_evaluations=9,
                accounts_with_evaluation=4,
            )

    assert (
        main(
            ["evaluations"],
            service=build_service(),
            evaluation_reader=EvaluationReader(),
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "approved_accounts": 5,
        "eligible_sessions": 12,
        "completed_evaluations": 9,
        "accounts_with_evaluation": 4,
    }
    assert "account_id" not in payload


def build_service() -> BetaAccessService:
    return BetaAccessService(
        repository=InMemoryBetaAccessRepository(),
        now=lambda: datetime(2030, 1, 1, tzinfo=UTC),
    )
