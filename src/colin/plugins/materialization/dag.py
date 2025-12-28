"""DAG materialization plugin using topological sort."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from colin.compiler.graph import DependencyGraph
    from colin.models import CompiledDocument


class DAGMaterializationPlugin:
    """Materialization plugin using topological sort on a DAG.

    This is the default materialization strategy. It compiles documents
    in topological order so dependencies are compiled before dependents.
    Documents in the same level are compiled in parallel.
    Fails if there are cycles in the graph.
    """

    name: str = "dag"

    async def materialize(
        self,
        changed: set[str],
        graph: DependencyGraph,
        compile_fn: Callable[[str], Awaitable[CompiledDocument]],
    ) -> list[str]:
        """Compile affected documents in topological order.

        Args:
            changed: Set of URIs that have changed.
            graph: The dependency graph.
            compile_fn: Function to compile a single document by URI.

        Returns:
            List of URIs that were compiled.

        Raises:
            CyclicDependencyError: If there are cycles in the graph.
        """
        if not changed:
            return []

        # Expand to include all downstream dependents
        affected = set(changed)
        for uri in changed:
            affected.update(graph.get_downstream(uri))

        # Filter to only URIs that exist in the graph
        all_uris = graph.get_all_uris()
        affected = affected & all_uris

        if not affected:
            return []

        # Get compilation order grouped by level (dependencies first)
        compile_order = graph.topological_sort(affected)

        # Compile each level in parallel
        compiled_uris: list[str] = []
        for level in compile_order:
            await asyncio.gather(*[compile_fn(uri) for uri in level])
            compiled_uris.extend(level)

        return compiled_uris
