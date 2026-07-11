from __future__ import annotations

import pytest

from music_recommender.product.account_service import (
    AccountDeletionConfirmationError,
    AccountDeletionNotFoundError,
    AccountService,
)


class FakeAccounts:
    def __init__(self) -> None:
        self.accounts = {"account-1"}

    def hard_delete(self, *, account_id: str) -> bool:
        if account_id not in self.accounts:
            return False
        self.accounts.remove(account_id)
        return True


def test_account_deletion_requires_exact_confirmation_and_hard_deletes() -> None:
    accounts = FakeAccounts()
    service = AccountService(accounts=accounts)

    with pytest.raises(AccountDeletionConfirmationError):
        service.delete(account_id="account-1", confirmation="delete")
    assert accounts.accounts == {"account-1"}

    service.delete(account_id="account-1", confirmation="DELETE")
    assert accounts.accounts == set()

    with pytest.raises(AccountDeletionNotFoundError):
        service.delete(account_id="account-1", confirmation="DELETE")
