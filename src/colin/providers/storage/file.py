"""Filesystem storage implementation."""

from datetime import datetime, timezone
from pathlib import Path

from colin.providers.storage.base import Storage


class FileStorage(Storage):
    """Filesystem storage with a base path.

    Reads and writes files relative to base_path.
    """

    def __init__(self, base_path: Path) -> None:
        """Initialize file storage.

        Args:
            base_path: Base directory for all reads/writes.
        """
        self.base_path = base_path.resolve()

    async def read(self, path: str) -> str:
        """Read file content.

        Args:
            path: Relative path within base_path.

        Returns:
            File content.

        Raises:
            FileNotFoundError: If file doesn't exist.
        """
        full_path = self.base_path / path
        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {path} (expected at {full_path})")
        return full_path.read_text(encoding="utf-8")

    async def write(self, path: str, content: str) -> None:
        """Write file content to relative path.

        Args:
            path: Relative path within base_path.
            content: Content to write.
        """
        full_path = self.base_path / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

    async def get_last_updated(self, path: str) -> datetime | None:
        """Get file modification time without reading content.

        Args:
            path: Relative path within base_path.

        Returns:
            File mtime as datetime, or None if file doesn't exist.
        """
        full_path = self.base_path / path
        if not full_path.exists():
            return None
        mtime = full_path.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc)
