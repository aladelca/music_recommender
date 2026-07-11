from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from fastapi.testclient import TestClient

from music_recommender.api.app import create_app
from music_recommender.api.dependencies import require_mutating_session
from music_recommender.storage.protocols import ApplicationSessionRecord


class FakeAccountService:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def delete(self, **kwargs: str) -> None:
        self.calls.append(kwargs)


def test_account_deletion_uses_session_account_and_clears_auth_cookies() -> None:
    service = FakeAccountService()
    app = create_app(
        load_env=False,
        auth_mode="hybrid",
        product_auth_service=cast(Any, object()),
        session_service=cast(Any, object()),
        csrf_protection=cast(Any, object()),
        account_service=service,
    )
    app.dependency_overrides[require_mutating_session] = session
    client = TestClient(app)

    response = client.request("DELETE", "/auth/me", json={"confirmation": "DELETE"})

    assert response.status_code == 204
    assert service.calls == [{"account_id": "account-1", "confirmation": "DELETE"}]
    cookies = response.headers.get_list("set-cookie")
    assert any("__Host-mr_session=" in value and "Max-Age=0" in value for value in cookies)
    assert any("__Host-mr_csrf=" in value and "Max-Age=0" in value for value in cookies)


def test_account_deletion_rejects_non_exact_confirmation_before_service() -> None:
    service = FakeAccountService()
    app = create_app(
        load_env=False,
        auth_mode="hybrid",
        product_auth_service=cast(Any, object()),
        session_service=cast(Any, object()),
        csrf_protection=cast(Any, object()),
        account_service=service,
    )
    app.dependency_overrides[require_mutating_session] = session

    response = TestClient(app).request(
        "DELETE",
        "/auth/me",
        json={"confirmation": "delete"},
    )

    assert response.status_code == 422
    assert service.calls == []


def session() -> ApplicationSessionRecord:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    return ApplicationSessionRecord(
        session_hash="a" * 64,
        account_id="account-1",
        csrf_hash="b" * 64,
        idle_expires_at=now + timedelta(days=7),
        absolute_expires_at=now + timedelta(days=30),
        last_seen_at=now,
        created_at=now,
    )
