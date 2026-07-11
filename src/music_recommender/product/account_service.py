from __future__ import annotations

from music_recommender.storage.protocols import AccountDeletionRepository


class AccountDeletionConfirmationError(ValueError):
    pass


class AccountDeletionNotFoundError(LookupError):
    pass


class AccountService:
    def __init__(self, *, accounts: AccountDeletionRepository) -> None:
        self.accounts = accounts

    def delete(self, *, account_id: str, confirmation: str) -> None:
        if confirmation != "DELETE":
            raise AccountDeletionConfirmationError(
                "Account deletion requires the exact confirmation DELETE."
            )
        if not self.accounts.hard_delete(account_id=account_id):
            raise AccountDeletionNotFoundError("Account was not found.")
