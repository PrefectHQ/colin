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

    def topological_sort(self, uris: set[str]) -> list[list[str]]:
        """Return URIs in compilation order, grouped by level.

        Documents in the same level have no dependencies on each other
        and can be compiled in parallel.

        Uses Kahn's algorithm for topological sort.

        Args:
            uris: Set of URIs to sort.

        Returns:
            List of levels, where each level is a list of URIs.

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
        result: list[list[str]] = []
        processed = 0

        while queue:
            # All items in queue form one level (no inter-dependencies)
            result.append(queue)
            processed += len(queue)
            next_queue = []

            for uri in queue:
                for dependent in self.dependents.get(uri, []):
                    if dependent in uris:
                        in_degree[dependent] -= 1
                        if in_degree[dependent] == 0:
                            next_queue.append(dependent)

            queue = next_queue

        if processed != len(uris):
            # Cycle detected - find the actual cycle path
            remaining = uris - {uri for level in result for uri in level}
            cycle_path = self._find_cycle(remaining)
            raise CyclicDependencyError(cycle_path)

        return result

    def _find_cycle(self, nodes: set[str]) -> list[str]:
        """Find a cycle in the given set of nodes using DFS.

        Args:
            nodes: Set of URIs known to be part of a cycle.

        Returns:
            List of URIs forming the cycle (e.g., [A, B, C] for A → B → C → A).
        """
        # Use DFS with path tracking to find the cycle.
        # path_set tracks the current DFS path for detecting back-edges (cycles).
        path: list[str] = []
        path_set: set[str] = set()

        def dfs(node: str) -> list[str] | None:
            if node in path_set:
                # Found cycle - extract it from path
                cycle_start = path.index(node)
                return path[cycle_start:]

            if node not in nodes:
                return None

            path.append(node)
            path_set.add(node)

            for dep in self.dependencies.get(node, []):
                if dep in nodes:
                    result = dfs(dep)
                    if result is not None:
                        return result

            path.pop()
            path_set.remove(node)
            return None

        # Start DFS from any node in the cycle
        for start in nodes:
            result = dfs(start)
            if result is not None:
                return result

        # Fallback (shouldn't happen if nodes truly contain a cycle)
        return list(nodes)

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
