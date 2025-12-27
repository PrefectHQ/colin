"""Base plugin protocols for Colin."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from colin.compiler.graph import DependencyGraph
    from colin.models import CompiledDocument, RefResult


class InputPlugin(Protocol):
    """Protocol for input plugins that fetch content from URI schemes."""

    scheme: str
    """URI scheme this plugin handles (e.g., 'file', 'mcp', 'colin')."""

    async def fetch(self, uri: str) -> RefResult:
        """Fetch content and metadata for a URI.

        Args:
            uri: The URI to fetch.

        Returns:
            RefResult with content and metadata.
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


class MaterializationPlugin(Protocol):
    """Protocol for materialization plugins that control compilation order."""

    name: str
    """Materialization strategy name (e.g., 'dag', 'bfs')."""

    async def materialize(
        self,
        changed: set[str],
        graph: DependencyGraph,
        compile_fn: Callable[[str], Awaitable[CompiledDocument]],
    ) -> list[str]:
        """Compile affected documents in appropriate order.

        Args:
            changed: Set of URIs that have changed.
            graph: The dependency graph.
            compile_fn: Function to compile a single document by URI.

        Returns:
            List of URIs that were compiled.
        """
        ...
