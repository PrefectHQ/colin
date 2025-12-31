"""Project provider for project:// URIs."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from colin.providers.base import Provider

if TYPE_CHECKING:
    from colin.models import Manifest


class ProjectProvider(Provider):
    """Provider for project:// URIs. Reads from compiled artifacts.

    Wraps another provider to provide the project:// scheme for template refs.
    The ref() function handles creating RefResult and tracking dependencies.

    By convention, instantiated with Storage (for artifact reads), but typed
    to accept any Provider since it only needs read capability.
    """

    scheme: str = "project"

    def __init__(self, provider: Provider, manifest: Manifest | None = None) -> None:
        """Initialize project provider.

        Args:
            provider: Underlying provider for reads (typically artifact storage).
            manifest: Optional manifest for timestamp lookups.
        """
        self._provider = provider
        self._manifest = manifest

    async def read(self, path: str) -> str:
        """Read compiled artifact by path.

        Args:
            path: Relative path (e.g., 'greeting.md').

        Returns:
            Raw content.
        """
        return await self._provider.read(path)

    async def get_last_updated(self, path: str) -> datetime | None:
        """Get compiled_at from manifest for a document.

        Args:
            path: Relative path (e.g., 'greeting.md').

        Returns:
            Document's compiled_at time, or None if not in manifest.
        """
        if self._manifest is None:
            return None
        uri = f"project://{path}"
        doc_meta = self._manifest.get_document(uri)
        if doc_meta is None:
            return None
        return doc_meta.compiled_at
