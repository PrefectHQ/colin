"""Encrypted OAuth token storage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
from key_value.aio.stores.disk import DiskStore

from colin.settings import settings

# OAuth token storage directory (shared between providers)
OAUTH_STORAGE_DIR = Path.home() / ".colin" / "mcp-oauth"


class EncryptedDiskStore:
    """DiskStore wrapper that encrypts values using Fernet.

    If no encryption key is configured, falls back to plain storage.
    """

    def __init__(self, directory: str) -> None:
        """Initialize the store.

        Args:
            directory: Directory path for the underlying DiskStore.
        """
        self._store = DiskStore(directory=directory)
        self._fernet: Fernet | None = None

        if settings.fernet_key:
            self._fernet = Fernet(settings.fernet_key.encode())

    async def get(self, key: str) -> Any:
        """Get a value, decrypting if encryption is enabled."""
        value = await self._store.get(key)
        if value is None:
            return None

        if self._fernet and isinstance(value, str):
            try:
                return self._fernet.decrypt(value.encode()).decode()
            except Exception:
                # If decryption fails, the value may be unencrypted (from before
                # encryption was enabled) or corrupted. Return None to trigger
                # re-authentication.
                return None

        return value

    async def set(self, key: str, value: str) -> None:
        """Set a value, encrypting if encryption is enabled."""
        if self._fernet:
            value = self._fernet.encrypt(value.encode()).decode()
        await self._store.set(key, value)  # type: ignore[union-attr]

    async def delete(self, key: str) -> None:
        """Delete a value."""
        await self._store.delete(key)


def get_oauth_store() -> EncryptedDiskStore:
    """Get the OAuth token store, creating the directory if needed.

    Returns:
        EncryptedDiskStore configured for OAuth tokens.
    """
    OAUTH_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    return EncryptedDiskStore(directory=str(OAUTH_STORAGE_DIR))
