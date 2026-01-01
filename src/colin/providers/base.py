"""Provider base class."""

from abc import abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, ConfigDict
from typing_extensions import Self

if TYPE_CHECKING:
    from colin.providers.addressable import Addressable


class Provider(BaseModel):
    """Base class for all providers.

    Providers expose template functions (via get_functions()) and support
    re-fetching from structured addresses (via load_address()).

    The `namespace` determines the template namespace (e.g., `s3`, `mcp.github`).

    Subclasses must:
    - Set `namespace` (class variable)
    - Implement `load_address()` for re-fetching from structured payloads

    The payload should include a 'type' field when the provider supports
    multiple addressable types, enabling TypeAdapter-based discrimination.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    namespace: ClassVar[str | None] = None
    """Template namespace for this provider (e.g., 's3', 'mcp')."""

    @abstractmethod
    async def load_address(self, payload: dict[str, Any]) -> "Addressable":
        """Load a resource from structured payload.

        Used for re-fetching resources from stored addresses and for
        staleness checking. The payload format is provider-specific.

        Args:
            payload: Provider-specific data for fetching the resource.
                     Should include 'type' field for discrimination when
                     provider has multiple addressable types.

        Returns:
            Addressable object with content and metadata.

        Raises:
            FileNotFoundError: If resource doesn't exist.
        """
        ...

    def get_functions(self) -> dict[str, Callable[..., Awaitable[object]]]:
        """Return template functions this provider contributes."""
        return {}

    async def get_last_updated(self, payload: dict[str, Any]) -> datetime | None:
        """Get last update time without loading full content.

        Override for efficient staleness detection (e.g., HEAD request,
        S3 metadata). Default loads the full resource.

        Args:
            payload: Provider-specific address payload.

        Returns:
            Last modification time, or None if unknown.
        """
        result = await self.load_address(payload)
        return result.last_updated

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        """Provider lifecycle hook for resource management."""
        yield

    @classmethod
    def from_config(cls, name: str | None, config: dict[str, Any]) -> Self:
        """Create provider instance from configuration."""
        return cls(**config)
