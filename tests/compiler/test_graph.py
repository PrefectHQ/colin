"""Tests for Colin dependency graph."""

from __future__ import annotations

import pytest

from colin.compiler.graph import DependencyGraph
from colin.exceptions import CyclicDependencyError


class TestDependencyGraph:
    def test_empty_graph(self) -> None:
        graph = DependencyGraph()
        assert graph.get_dependencies("any") == []
        assert graph.get_dependents("any") == []

    def test_add_edge(self) -> None:
        graph = DependencyGraph()
        graph.add_edge("a", "b")

        assert graph.get_dependencies("a") == ["b"]
        assert graph.get_dependents("b") == ["a"]

    def test_add_edge_deduplication(self) -> None:
        graph = DependencyGraph()
        graph.add_edge("a", "b")
        graph.add_edge("a", "b")

        assert graph.get_dependencies("a") == ["b"]

    def test_multiple_dependencies(self) -> None:
        graph = DependencyGraph()
        graph.add_edge("a", "b")
        graph.add_edge("a", "c")

        deps = graph.get_dependencies("a")
        assert set(deps) == {"b", "c"}

    def test_multiple_dependents(self) -> None:
        graph = DependencyGraph()
        graph.add_edge("a", "c")
        graph.add_edge("b", "c")

        dependents = graph.get_dependents("c")
        assert set(dependents) == {"a", "b"}

    def test_topological_sort_linear(self) -> None:
        graph = DependencyGraph()
        graph.add_edge("c", "b")
        graph.add_edge("b", "a")

        result = graph.topological_sort({"a", "b", "c"})
        assert result.index("a") < result.index("b")
        assert result.index("b") < result.index("c")

    def test_topological_sort_diamond(self) -> None:
        graph = DependencyGraph()
        graph.add_edge("d", "b")
        graph.add_edge("d", "c")
        graph.add_edge("b", "a")
        graph.add_edge("c", "a")

        result = graph.topological_sort({"a", "b", "c", "d"})
        assert result.index("a") < result.index("b")
        assert result.index("a") < result.index("c")
        assert result.index("b") < result.index("d")
        assert result.index("c") < result.index("d")

    def test_topological_sort_independent(self) -> None:
        graph = DependencyGraph()
        result = graph.topological_sort({"a", "b", "c"})
        assert set(result) == {"a", "b", "c"}

    def test_topological_sort_cycle_detection(self) -> None:
        graph = DependencyGraph()
        graph.add_edge("a", "b")
        graph.add_edge("b", "c")
        graph.add_edge("c", "a")

        with pytest.raises(CyclicDependencyError) as exc_info:
            graph.topological_sort({"a", "b", "c"})
        assert "Cyclic dependency" in str(exc_info.value)

    def test_topological_sort_self_cycle(self) -> None:
        graph = DependencyGraph()
        graph.add_edge("a", "a")

        with pytest.raises(CyclicDependencyError):
            graph.topological_sort({"a"})

    def test_get_downstream_direct(self) -> None:
        graph = DependencyGraph()
        graph.add_edge("b", "a")
        graph.add_edge("c", "a")

        downstream = graph.get_downstream("a")
        assert downstream == {"b", "c"}

    def test_get_downstream_transitive(self) -> None:
        graph = DependencyGraph()
        graph.add_edge("b", "a")
        graph.add_edge("c", "b")
        graph.add_edge("d", "c")

        downstream = graph.get_downstream("a")
        assert downstream == {"b", "c", "d"}

    def test_get_downstream_empty(self) -> None:
        graph = DependencyGraph()
        graph.add_edge("a", "b")

        assert graph.get_downstream("a") == set()

    def test_get_all_uris(self) -> None:
        graph = DependencyGraph()
        graph.add_edge("a", "b")
        graph.add_edge("c", "d")

        uris = graph.get_all_uris()
        assert uris == {"a", "b", "c", "d"}
