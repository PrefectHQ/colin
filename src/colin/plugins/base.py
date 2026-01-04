"""Base plugin protocols for Colin."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from colin.models import CompiledDocument
    from colin.resources import Resource


class InputPlugin(Protocol):
    """Protocol for input plugins that fetch content from URI schemes."""

    scheme: str
    """URI scheme this plugin handles (e.g., 'file', 'mcp', 'colin')."""

    async def fetch(self, uri: str) -> Resource:
        """Fetch content and metadata for a URI.

        Args:
            uri: The URI to fetch.

        Returns:
            Resource object with content and metadata.
        """
        ...

    async def hash(self, uri: str) -> str:
        """Get content hash for change detection.

        Args:
            uri: The URI to hash.

        Returns:
            A hash string representing the content.
        """
        ...


class OutputPlugin(Protocol):
    """Protocol for output plugins that write compiled documents."""

    name: str
    """Output format name (e.g., 'markdown', 'skill')."""

    async def emit(
        self,
        doc: CompiledDocument,
        output_dir: Path,
    ) -> list[Path]:
        """Write compiled document to output directory.

        Args:
            doc: The compiled document.
            output_dir: Base output directory.

        Returns:
            List of paths that were written.
        """
        ...
