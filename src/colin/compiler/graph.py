"""Dependency graph for Colin documents."""

from __future__ import annotations

from collections import defaultdict

from colin.exceptions import CyclicDependencyError


class DependencyGraph:
    """Builds and traverses the dependency graph.

    The graph tracks which documents depend on which other documents.
    Edges go from dependent → dependency (A depends on B means A → B).
    """

    def __init__(self) -> None:
        """Initialize an empty dependency graph."""
        # uri → list of URIs this document depends on
        self.dependencies: dict[str, list[str]] = defaultdict(list)
        # uri → list of URIs that depend on this document
        self.dependents: dict[str, list[str]] = defaultdict(list)

    def add_edge(self, from_uri: str, to_uri: str) -> None:
        """Add a dependency edge: from_uri depends on to_uri.

        Args:
            from_uri: The dependent document URI.
            to_uri: The dependency document URI.
        """
        if to_uri not in self.dependencies[from_uri]:
            self.dependencies[from_uri].append(to_uri)
        if from_uri not in self.dependents[to_uri]:
            self.dependents[to_uri].append(from_uri)

    def get_dependencies(self, uri: str) -> list[str]:
        """Get direct dependencies of a document.

        Args:
            uri: Document URI.

        Returns:
            List of URIs this document depends on.
        """
        return self.dependencies.get(uri, [])

    def get_dependents(self, uri: str) -> list[str]:
        """Get direct dependents of a document.

        Args:
            uri: Document URI.

        Returns:
            List of URIs that depend on this document.
        """
        return self.dependents.get(uri, [])

    def topological_sort(self, uris: set[str]) -> list[str]:
        """Return URIs in compilation order (dependencies first).

        Uses Kahn's algorithm for topological sort.

        Args:
            uris: Set of URIs to sort.

        Returns:
            List of URIs in topological order.

        Raises:
            CyclicDependencyError: If a cycle is detected.
        """
        # Build in-degree map for the subgraph
        in_degree: dict[str, int] = {uri: 0 for uri in uris}

        for uri in uris:
            for dep in self.dependencies.get(uri, []):
                if dep in uris:
                    in_degree[uri] += 1

        # Start with nodes that have no dependencies
        queue = [uri for uri, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            uri = queue.pop(0)
            result.append(uri)

            # Reduce in-degree for dependents
            for dependent in self.dependents.get(uri, []):
                if dependent in uris:
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        queue.append(dependent)

        if len(result) != len(uris):
            # Cycle detected
            remaining = uris - set(result)
            raise CyclicDependencyError(f"Cyclic dependency involving: {remaining}")

        return result

    def get_downstream(self, uri: str) -> set[str]:
        """Get all documents that transitively depend on uri.

        Args:
            uri: Document URI.

        Returns:
            Set of URIs that depend on this document (directly or transitively).
        """
        visited: set[str] = set()
        stack = [uri]

        while stack:
            current = stack.pop()
            for dependent in self.dependents.get(current, []):
                if dependent not in visited:
                    visited.add(dependent)
                    stack.append(dependent)

        return visited

    def get_all_uris(self) -> set[str]:
        """Get all URIs in the graph.

        Returns:
            Set of all URIs that appear in the graph.
        """
        all_uris: set[str] = set()
        all_uris.update(self.dependencies.keys())
        all_uris.update(self.dependents.keys())
        return all_uris
