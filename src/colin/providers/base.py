"""Provider base class for URI handlers."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime


class Provider(ABC):
    """Base class for all providers. Low-level I/O for URI schemes.

    Providers handle reading content from URIs. The `schemes` list defines
    which URI schemes route to this provider. The `namespace` is used for
    template namespaces and config (defaults to schemes[0]).

    Returns raw content (str), not RefResult. The ref() function handles
    wrapping content in RefResult and tracking dependencies.

    Subclasses must set `schemes` (at least one) and implement `read()`.
    """

    schemes: list[str] = []
    """URI schemes this provider handles for routing."""

    namespace: str | None = None
    """Template/config namespace. Auto-set to schemes[0] if not specified."""

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # Auto-set namespace from schemes[0] if not explicitly set
        if cls.namespace is None and cls.schemes:
            cls.namespace = cls.schemes[0]

    @abstractmethod
    async def read(self, uri: str) -> str:
        """Read content from URI.

        Args:
            uri: Full URI including scheme (e.g., 'https://example.com/data').

        Returns:
            Raw content as string.

        Raises:
            FileNotFoundError: If resource doesn't exist.
        """
        ...

    def get_functions(self) -> dict[str, Callable[..., Awaitable[object]]]:
        """Return template functions this provider contributes."""
        return {}

    async def get_last_updated(self, uri: str) -> datetime | None:
        """Get last update time for a resource without reading content.

        This enables efficient staleness detection. Providers should override
        this to return timestamps without loading full content (e.g., file mtime,
        HTTP HEAD request, manifest lookup).

        Args:
            uri: Full URI including scheme.

        Returns:
            Last update time, or None if unknown. None means "treat as stale".
        """
        return None

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        """Provider lifecycle hook for resource management.

        Override this to manage resources like database connections or HTTP clients.
        The manager enters this context at startup and exits at shutdown.

        Example:
            @asynccontextmanager
            async def lifespan(self) -> AsyncIterator[None]:
                async with httpx.AsyncClient() as client:
                    self._client = client
                    yield
        """
        yield
