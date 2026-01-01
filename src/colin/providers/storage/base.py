"""Storage base class for reading and writing artifacts."""

from abc import ABC, abstractmethod
from datetime import datetime


class Storage(ABC):
    """Base class for storage backends.

    Storage provides read/write access to artifacts. Used internally
    by ProjectProvider for reading compiled outputs and by output
    plugins for writing artifacts.

    Takes relative paths, knows its base location internally.
    """

    @abstractmethod
    async def read(self, path: str) -> str:
        """Read content from relative path.

        Args:
            path: Relative path within storage.

        Returns:
            File content.

        Raises:
            FileNotFoundError: If file doesn't exist.
        """
        ...

    @abstractmethod
    async def write(self, path: str, content: str) -> None:
        """Write content to relative path.

        Args:
            path: Relative path within storage.
            content: Content to write.
        """
        ...

    async def get_last_updated(self, path: str) -> datetime | None:
        """Get last modified time for a path.

        Args:
            path: Relative path within storage.

        Returns:
            Modification time, or None if not available.
        """
        return None
