"""OS credential storage. Never store bearer tokens in connection profiles."""
from __future__ import annotations

import keyring
from keyring.errors import KeyringError


SERVICE = "Morphorum-Studio/backend-client"


class CredentialStore:
    def __init__(self, backend=None):
        self._backend = backend or keyring

    def get(self, profile_id: str) -> str | None:
        try:
            return self._backend.get_password(SERVICE, profile_id)
        except KeyringError as exc:
            raise RuntimeError("OS credential store unavailable") from exc

    def set(self, profile_id: str, token: str) -> None:
        if not token or "\n" in token or "\r" in token:
            raise ValueError("Invalid token")
        try:
            self._backend.set_password(SERVICE, profile_id, token)
        except KeyringError as exc:
            raise RuntimeError("Unable to save token securely in OS credential store") from exc

    def delete(self, profile_id: str) -> None:
        try:
            if self.get(profile_id) is not None:
                self._backend.delete_password(SERVICE, profile_id)
        except KeyringError as exc:
            raise RuntimeError("Unable to remove saved token") from exc
