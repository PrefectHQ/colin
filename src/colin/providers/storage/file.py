"""Filesystem storage implementation."""

from datetime import datetime, timezone
from pathlib import Path

from colin.providers.storage.base import Storage


class FileStorage(Storage):
    """Filesystem storage with a base path.

    Reads and writes files relative to base_path.
    """

    schemes: list[str] = ["file"]
    base_path: Path

    def __init__(self, base_path: Path) -> None:
        """Initialize file storage.

        Args:
            base_path: Base directory for all reads/writes.
        """
        resolved = base_path.resolve()
        super().__init__(base_path=resolved)  # type: ignore[call-arg]

    def _extract_path(self, uri: str) -> str:
        """Extract path from URI, stripping scheme if present."""
        return uri.split("://", 1)[1] if "://" in uri else uri

    async def read(self, uri: str) -> str:
        """Read file content.

        Args:
            uri: Full URI (e.g., 'file://path/to/file') or relative path.

        Returns:
            File content.

        Raises:
            FileNotFoundError: If file doesn't exist.
        """
        path = self._extract_path(uri)
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

    async def get_last_updated(self, uri: str) -> datetime | None:
        """Get file modification time without reading content.

        Args:
            uri: Full URI or relative path.

        Returns:
            File mtime as datetime, or None if file doesn't exist.
        """
        path = self._extract_path(uri)
        full_path = self.base_path / path
        if not full_path.exists():
            return None
        mtime = full_path.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc)
