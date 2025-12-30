"""Storage base class for reading and writing artifacts."""

from abc import abstractmethod

from colin.providers.base import Provider


class Storage(Provider):
    """Provider that also supports writing. Used for artifacts.

    Storage extends Provider with write capability. Used for both
    reading compiled outputs (via ProjectProvider) and writing new artifacts.

    Takes relative paths, knows its base location internally.
    """

    @abstractmethod
    async def write(self, path: str, content: str) -> None:
        """Write content to relative path.

        Args:
            path: Relative path within storage.
            content: Content to write.
        """
        ...
