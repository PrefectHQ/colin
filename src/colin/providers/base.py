"""Provider base class for URI handlers."""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable


class Provider(ABC):
    """Base class for all providers. Low-level I/O for a URI scheme.

    Providers handle reading content from a URI scheme. The scheme is used
    for routing (e.g., 'project', 'mcp.linear'), and read() receives just
    the path portion after scheme stripping.

    Returns raw content (str), not RefResult. The ref() function handles
    wrapping content in RefResult and tracking dependencies.

    Subclasses must set `scheme` and implement `read()`.
    """

    scheme: str
    """URI scheme this provider handles (e.g., 'project', 's3', 'mcp.linear')."""

    @abstractmethod
    async def read(self, path: str) -> str:
        """Read content from path.

        Args:
            path: Path portion of URI (scheme already stripped).

        Returns:
            Raw content as string.

        Raises:
            FileNotFoundError: If resource doesn't exist.
        """
        ...

    def get_functions(self) -> dict[str, Callable[..., Awaitable[object]]]:
        """Return template functions this provider contributes."""
        return {}
