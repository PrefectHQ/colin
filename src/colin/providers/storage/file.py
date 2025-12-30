"""Filesystem storage implementation."""

from pathlib import Path

from colin.providers.storage.base import Storage


class FileStorage(Storage):
    """Filesystem storage with a base path.

    Reads and writes files relative to base_path.
    """

    scheme: str = "file"

    def __init__(self, base_path: Path) -> None:
        """Initialize file storage.

        Args:
            base_path: Base directory for all reads/writes.
        """
        self.base_path = base_path.resolve()

    async def read(self, path: str) -> str:
        """Read file content from relative path.

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
