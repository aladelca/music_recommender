from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError

from music_recommender.security.token_vault import KmsTokenVault, TokenVaultError


class FakeKmsClient:
    def __init__(self) -> None:
        self.encrypt_calls: list[dict[str, Any]] = []
        self.decrypt_calls: list[dict[str, Any]] = []
        self.encrypt_response: dict[str, Any] = {"CiphertextBlob": b"encrypted-token"}
        self.decrypt_response: dict[str, Any] = {"Plaintext": b"refresh-token"}
        self.error: Exception | None = None

    def encrypt(self, **kwargs: Any) -> dict[str, Any]:
        self.encrypt_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.encrypt_response

    def decrypt(self, **kwargs: Any) -> dict[str, Any]:
        self.decrypt_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.decrypt_response


def test_kms_token_vault_binds_ciphertext_to_account_context() -> None:
    kms = FakeKmsClient()
    vault = KmsTokenVault(kms_client=kms, key_id="alias/outside-the-loop-spotify")

    ciphertext = vault.encrypt_refresh_token(
        account_id="spotify-account",
        refresh_token="refresh-token",
    )
    plaintext = vault.decrypt_refresh_token(
        account_id="spotify-account",
        ciphertext=ciphertext,
    )

    context = {
        "purpose": "spotify_refresh_token",
        "account_id": "spotify-account",
    }
    assert ciphertext == b"encrypted-token"
    assert plaintext == "refresh-token"
    assert kms.encrypt_calls == [
        {
            "KeyId": "alias/outside-the-loop-spotify",
            "Plaintext": b"refresh-token",
            "EncryptionContext": context,
            "EncryptionAlgorithm": "SYMMETRIC_DEFAULT",
        }
    ]
    assert kms.decrypt_calls == [
        {
            "KeyId": "alias/outside-the-loop-spotify",
            "CiphertextBlob": b"encrypted-token",
            "EncryptionContext": context,
            "EncryptionAlgorithm": "SYMMETRIC_DEFAULT",
        }
    ]


def test_kms_token_vault_binds_pkce_verifier_to_oauth_state() -> None:
    kms = FakeKmsClient()
    kms.decrypt_response = {"Plaintext": b"code-verifier"}
    vault = KmsTokenVault(kms_client=kms, key_id="alias/outside-the-loop-spotify")

    ciphertext = vault.encrypt_oauth_verifier(
        state_hash="a" * 64,
        code_verifier="code-verifier",
    )
    verifier = vault.decrypt_oauth_verifier(
        state_hash="a" * 64,
        ciphertext=ciphertext,
    )

    context = {
        "purpose": "spotify_oauth_verifier",
        "state_hash": "a" * 64,
    }
    assert verifier == "code-verifier"
    assert kms.encrypt_calls[0]["EncryptionContext"] == context
    assert kms.decrypt_calls[0]["EncryptionContext"] == context


@pytest.mark.parametrize(
    ("account_id", "refresh_token", "message"),
    [
        ("", "refresh-token", "account_id must not be empty"),
        ("spotify-account", "", "refresh_token must not be empty"),
    ],
)
def test_kms_token_vault_rejects_empty_inputs(
    account_id: str,
    refresh_token: str,
    message: str,
) -> None:
    vault = KmsTokenVault(
        kms_client=FakeKmsClient(),
        key_id="alias/outside-the-loop-spotify",
    )

    with pytest.raises(ValueError, match=message):
        vault.encrypt_refresh_token(account_id=account_id, refresh_token=refresh_token)


def test_kms_token_vault_redacts_aws_error_details() -> None:
    kms = FakeKmsClient()
    kms.error = ClientError(
        {
            "Error": {
                "Code": "AccessDeniedException",
                "Message": "refresh-secret must not appear",
            }
        },
        "Encrypt",
    )
    vault = KmsTokenVault(kms_client=kms, key_id="alias/private-key-name")

    with pytest.raises(TokenVaultError, match="Spotify credential protection failed") as error:
        vault.encrypt_refresh_token(
            account_id="spotify-account",
            refresh_token="refresh-secret",
        )

    assert "refresh-secret" not in str(error.value)
    assert "private-key-name" not in str(error.value)


def test_kms_token_vault_rejects_invalid_decrypted_payload() -> None:
    kms = FakeKmsClient()
    kms.decrypt_response = {"Plaintext": b"\xff"}
    vault = KmsTokenVault(kms_client=kms, key_id="alias/outside-the-loop-spotify")

    with pytest.raises(TokenVaultError, match="Spotify credential protection failed"):
        vault.decrypt_refresh_token(
            account_id="spotify-account",
            ciphertext=b"ciphertext",
        )
