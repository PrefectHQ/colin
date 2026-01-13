"""Provider base class."""

import hashlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, ConfigDict
from typing_extensions import Self

from colin.exceptions import RefError

if TYPE_CHECKING:
    from colin.models import Ref
    from colin.resources import Resource


# Sentinel hash for built-in providers with no user configuration
BUILTIN_CONFIG_HASH = "0" * 16


class Provider(BaseModel):
    """Base class for all providers.

    Providers expose template functions (via get_functions()) and support
    re-fetching from Refs (via _load_ref()).

    The `namespace` determines the template namespace (e.g., `s3`, `mcp.github`).

    Subclasses should:
    - Set `namespace` (class variable)
    - Implement template functions that return Resource objects
    - Optionally override `get_ref_version()` for efficient staleness checks
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    namespace: ClassVar[str | None] = None
    """Template namespace for this provider (e.g., 's3', 'mcp')."""

    _connection: str = ""
    """Instance/connection name (e.g., 'prod' for s3.prod). Set by from_config()."""

    _config_hash: str = ""
    """Hash of provider config for cache key inclusion. Set by from_config()."""

    def get_functions(self) -> dict[str, Callable[..., Awaitable[object]]]:
        """Return template functions this provider contributes."""
        return {}

    async def _load_ref(self, ref: "Ref") -> "Resource":
        """Load a resource from a Ref by calling the method with stored args.

        Default implementation uses getattr to find the method and calls it
        with watch=False (to avoid re-tracking during staleness check).

        Args:
            ref: The Ref containing method name and args.

        Returns:
            Resource object with content and version.

        Raises:
            RefError: If the method doesn't exist on this provider.
        """
        if not hasattr(self, ref.method):
            raise RefError(f"Unknown method on {self.namespace} provider: {ref.method}")
        method = getattr(self, ref.method)
        return await method(**ref.args, watch=False)

    async def get_ref_version(self, ref: "Ref") -> str:
        """Get current version for a ref.

        Override for efficiency (e.g., HEAD request for ETag, stat for mtime).
        Default loads the full resource via _load_ref().

        Args:
            ref: The Ref to check.

        Returns:
            Current version string for comparison.
        """
        resource = await self._load_ref(ref)
        return resource.version

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        """Provider lifecycle hook for resource management."""
        yield

    @classmethod
    def from_config(cls, name: str | None, config: dict[str, Any]) -> Self:
        """Create provider instance from configuration.

        Args:
            name: Instance name (e.g., 'prod' for s3.prod). Stored in _connection.
            config: Provider-specific configuration.

        Returns:
            Configured provider instance.
        """

        instance = cls(**config)
        instance._connection = name or ""
        # Store config hash for cache key inclusion
        config_str = json.dumps(config, sort_keys=True)
        instance._config_hash = hashlib.sha256(config_str.encode()).hexdigest()[:16]
        return instance
