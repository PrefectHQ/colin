"""File provider for reading files from the filesystem."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

from colin.models import Address
from colin.providers.addressable import Addressable
from colin.providers.base import Provider


@dataclass
class FileResource(Addressable):
    """Domain object returned by FileProvider. Inherits from Addressable."""

    path: str
    """Absolute path to the file."""

    _content: str
    """File content."""

    _last_updated: datetime | None = None
    """File modification time."""

    _instance: str = field(default="", repr=False)
    """Provider instance name."""

    @property
    def content(self) -> str:
        return self._content

    @property
    def last_updated(self) -> datetime:
        return self._last_updated or datetime.now(timezone.utc)

    def address(self) -> Address:
        return Address(
            provider="file",
            instance=self._instance,
            payload={"path": self.path},
        )


class FileProvider(Provider):
    """Provider for reading files from the filesystem.

    Template usage: {{ file.get("/path/to/file.txt") }}
    """

    namespace: ClassVar[str] = "file"

    _instance: str = ""

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        yield

    async def load_address(self, payload: dict[str, Any]) -> FileResource:
        """Load file from address payload.

        Args:
            payload: Dict with 'path' key (absolute path).

        Returns:
            FileResource with content and metadata.
        """
        path = payload["path"]
        return await self._fetch(path)

    async def _fetch(self, path: str) -> FileResource:
        """Fetch file content."""
        expanded = os.path.expanduser(path)
        resolved = Path(expanded).resolve()

        if not resolved.exists():
            raise FileNotFoundError(f"File not found: {path}")

        content = resolved.read_text(encoding="utf-8")
        mtime = resolved.stat().st_mtime
        last_updated = datetime.fromtimestamp(mtime, tz=timezone.utc)

        return FileResource(
            path=str(resolved),
            _content=content,
            _last_updated=last_updated,
            _instance=self._instance,
        )

    async def get_last_updated(self, payload: dict[str, Any]) -> datetime | None:
        """Get file modification time.

        Args:
            payload: Dict with 'path' key.

        Returns:
            File mtime as datetime, or None if file doesn't exist.
        """
        path = payload["path"]
        expanded = os.path.expanduser(path)
        resolved = Path(expanded).resolve()

        if not resolved.exists():
            return None

        mtime = resolved.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc)

    def get_functions(self) -> dict[str, Callable[..., Awaitable[object]]]:
        return {"get": self.get}

    async def get(self, path: str) -> FileResource:
        """Read a file from the filesystem.

        Template usage: {{ file.get("/path/to/file.txt") }}

        Args:
            path: Absolute or ~ path to the file.

        Returns:
            FileResource with content and metadata.
        """
        return await self._fetch(path)
