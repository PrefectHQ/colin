"""Project provider for project:// URIs."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from colin.providers.base import Provider

if TYPE_CHECKING:
    from colin.models import Manifest
    from colin.providers.storage.base import Storage


class ProjectProvider(Provider):
    """Provider for project:// URIs. Reads from compiled artifacts.

    Wraps Storage to provide the project:// scheme for template refs.
    The ref() function handles creating RefResult and tracking dependencies.
    """

    schemes: list[str] = ["project"]

    def __init__(self, storage: Storage, manifest: Manifest | None = None) -> None:
        """Initialize project provider.

        Args:
            storage: Storage for artifact reads.
            manifest: Optional manifest for timestamp lookups.
        """
        self._storage = storage
        self._manifest = manifest

    async def read(self, uri: str) -> str:
        """Read compiled artifact by URI.

        Args:
            uri: Full URI (e.g., 'project://greeting.md').

        Returns:
            Raw content.
        """
        path = uri.split("://", 1)[1] if "://" in uri else uri
        return await self._storage.read(path)

    async def get_last_updated(self, uri: str) -> datetime | None:
        """Get compiled_at from manifest for a document.

        Args:
            uri: Full URI (e.g., 'project://greeting.md').

        Returns:
            Document's compiled_at time, or None if not in manifest.
        """
        if self._manifest is None:
            return None
        doc_meta = self._manifest.get_document(uri)
        if doc_meta is None:
            return None
        return doc_meta.compiled_at
