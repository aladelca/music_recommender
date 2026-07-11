from __future__ import annotations

from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from music_recommender.config import Settings


class TokenVaultError(RuntimeError):
    """A redacted Spotify token encryption or decryption failure."""


class KmsTokenVault:
    def __init__(self, *, kms_client: Any, key_id: str) -> None:
        normalized_key_id = key_id.strip()
        if not normalized_key_id:
            raise ValueError("key_id must not be empty.")
        self.kms_client = kms_client
        self.key_id = normalized_key_id

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        kms_client: Any | None = None,
    ) -> KmsTokenVault:
        if settings.spotify_token_kms_key_id is None:
            raise ValueError("SPOTIFY_TOKEN_KMS_KEY_ID is required for Spotify token storage.")
        if kms_client is None:
            import boto3

            kms_client = boto3.client("kms", region_name=settings.aws_region)
        return cls(kms_client=kms_client, key_id=settings.spotify_token_kms_key_id)

    def encrypt_refresh_token(self, *, account_id: str, refresh_token: str) -> bytes:
        normalized_account_id = _required_text(account_id, "account_id")
        return self._encrypt_secret(
            value=refresh_token,
            value_name="refresh_token",
            encryption_context=_refresh_token_context(normalized_account_id),
        )

    def decrypt_refresh_token(self, *, account_id: str, ciphertext: bytes) -> str:
        normalized_account_id = _required_text(account_id, "account_id")
        if not ciphertext:
            raise ValueError("ciphertext must not be empty.")
        return self._decrypt_secret(
            ciphertext=ciphertext,
            encryption_context=_refresh_token_context(normalized_account_id),
        )

    def encrypt_oauth_verifier(self, *, state_hash: str, code_verifier: str) -> bytes:
        normalized_state_hash = _sha256_hash(state_hash, "state_hash")
        return self._encrypt_secret(
            value=code_verifier,
            value_name="code_verifier",
            encryption_context=_oauth_verifier_context(normalized_state_hash),
        )

    def decrypt_oauth_verifier(self, *, state_hash: str, ciphertext: bytes) -> str:
        normalized_state_hash = _sha256_hash(state_hash, "state_hash")
        return self._decrypt_secret(
            ciphertext=ciphertext,
            encryption_context=_oauth_verifier_context(normalized_state_hash),
        )

    def _encrypt_secret(
        self,
        *,
        value: str,
        value_name: str,
        encryption_context: dict[str, str],
    ) -> bytes:
        normalized_value = _required_text(value, value_name)
        if len(normalized_value.encode("utf-8")) > 4_096:
            raise ValueError(f"{value_name} must not exceed 4096 bytes.")
        try:
            response = self.kms_client.encrypt(
                KeyId=self.key_id,
                Plaintext=normalized_value.encode("utf-8"),
                EncryptionContext=encryption_context,
                EncryptionAlgorithm="SYMMETRIC_DEFAULT",
            )
            ciphertext = response.get("CiphertextBlob")
            if not isinstance(ciphertext, bytes) or not ciphertext:
                raise TokenVaultError("Spotify credential protection failed.")
            return ciphertext
        except (BotoCoreError, ClientError):
            raise TokenVaultError("Spotify credential protection failed.") from None

    def _decrypt_secret(
        self,
        *,
        ciphertext: bytes,
        encryption_context: dict[str, str],
    ) -> str:
        if not ciphertext:
            raise ValueError("ciphertext must not be empty.")
        try:
            response = self.kms_client.decrypt(
                KeyId=self.key_id,
                CiphertextBlob=ciphertext,
                EncryptionContext=encryption_context,
                EncryptionAlgorithm="SYMMETRIC_DEFAULT",
            )
            plaintext = response.get("Plaintext")
            if not isinstance(plaintext, bytes) or not plaintext:
                raise TokenVaultError("Spotify credential protection failed.")
            return plaintext.decode("utf-8")
        except (BotoCoreError, ClientError, UnicodeDecodeError):
            raise TokenVaultError("Spotify credential protection failed.") from None


def _required_text(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty.")
    return normalized


def _refresh_token_context(account_id: str) -> dict[str, str]:
    return {
        "purpose": "spotify_refresh_token",
        "account_id": account_id,
    }


def _oauth_verifier_context(state_hash: str) -> dict[str, str]:
    return {
        "purpose": "spotify_oauth_verifier",
        "state_hash": state_hash,
    }


def _sha256_hash(value: str, name: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{name} must be a SHA-256 hexadecimal digest.")
    return normalized
