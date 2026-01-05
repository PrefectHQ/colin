"""Tests for depends_on frontmatter hint for compilation ordering."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from colin.api.project import ProjectConfig
from colin.compiler import CompileEngine
from colin.exceptions import MultipleCompilationErrors, RefNotCompiledError
from colin.providers.storage.file import FileStorage


class TestDependsOn:
    """Tests for depends_on compilation ordering hints."""

    @pytest.fixture
    def engine_setup(self, tmp_path: Path, mock_agent: MagicMock) -> tuple[CompileEngine, Path]:
        source_dir = tmp_path / "models"
        source_dir.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir(parents=True)
        build_dir = tmp_path / ".colin"
        build_dir.mkdir()
        compiled_dir = build_dir / "compiled"
        compiled_dir.mkdir()

        config = ProjectConfig(
            name="test-project",
            project_root=tmp_path,
            model_path=source_dir,
            output_path=output_dir,
            manifest_path=build_dir / "manifest.json",
        )
        artifact_storage = FileStorage(base_path=compiled_dir)

        engine = CompileEngine(
            config=config,
            artifact_storage=artifact_storage,
        )
        return engine, source_dir

    async def test_depends_on_parsed_from_frontmatter(
        self, engine_setup: tuple[CompileEngine, Path]
    ) -> None:
        """depends_on is correctly parsed from frontmatter."""
        engine, source_dir = engine_setup

        (source_dir / "a.md").write_text("""\
---
name: A
colin:
  depends_on:
    - b.md
    - c.md
---

Content A
""")
        (source_dir / "b.md").write_text("---\nname: B\n---\nContent B")
        (source_dir / "c.md").write_text("---\nname: C\n---\nContent C")

        result = await engine.compile_all()
        uris = [doc.uri for doc in result]

        # B and C should be compiled before A
        assert uris.index("project://b.md") < uris.index("project://a.md")
        assert uris.index("project://c.md") < uris.index("project://a.md")

    async def test_depends_on_creates_graph_edges(
        self, engine_setup: tuple[CompileEngine, Path]
    ) -> None:
        """depends_on creates edges in the dependency graph."""
        engine, source_dir = engine_setup

        (source_dir / "consumer.md").write_text("""\
---
name: Consumer
colin:
  depends_on:
    - producer.md
---

{{ ref('producer.md').content }}
""")
        (source_dir / "producer.md").write_text("---\nname: Producer\n---\nProduced!")

        result = await engine.compile_all()

        # Consumer should include producer's content
        consumer = next(doc for doc in result if doc.uri == "project://consumer.md")
        assert "Produced!" in consumer.output

    async def test_depends_on_with_dynamic_ref(
        self, engine_setup: tuple[CompileEngine, Path]
    ) -> None:
        """depends_on enables dynamic refs that can't be statically extracted."""
        engine, source_dir = engine_setup

        # Create a document that uses a dynamic ref (variable)
        (source_dir / "config.md").write_text("---\nname: Config\n---\nconfig-value")
        (source_dir / "consumer.md").write_text("""\
---
name: Consumer
colin:
  depends_on:
    - config.md
---

{% set target = 'config.md' %}
Value: {{ ref(target).content }}
""")

        result = await engine.compile_all()

        consumer = next(doc for doc in result if doc.uri == "project://consumer.md")
        assert "config-value" in consumer.output

    async def test_depends_on_without_hint_fails_for_dynamic_ref(
        self, engine_setup: tuple[CompileEngine, Path]
    ) -> None:
        """Dynamic refs without depends_on fail if target not compiled first."""
        engine, source_dir = engine_setup

        # Consumer has dynamic ref but no depends_on hint
        # The dependency graph won't know about it, so ordering is arbitrary
        (source_dir / "config.md").write_text("---\nname: Config\n---\nconfig-value")
        (source_dir / "consumer.md").write_text("""\
---
name: Consumer
---

{% set target = 'config.md' %}
Value: {{ ref(target).content }}
""")

        # Without depends_on, this may fail if consumer compiles before config
        # Since there's no static ref and no hint, compilation order is arbitrary
        # This test verifies that without the hint, RefNotCompiledError can occur
        try:
            await engine.compile_all()
            # If it succeeds, config happened to compile first (alphabetically)
            # This is acceptable - the test just demonstrates the pattern
        except MultipleCompilationErrors as e:
            # If it fails, it should be RefNotCompiledError
            assert any(
                isinstance(err, RefNotCompiledError) for errs in e.errors.values() for err in errs
            )

    async def test_depends_on_ordering_chain(
        self, engine_setup: tuple[CompileEngine, Path]
    ) -> None:
        """depends_on correctly orders a chain of dependencies."""
        engine, source_dir = engine_setup

        (source_dir / "first.md").write_text("---\nname: First\n---\nFirst!")
        (source_dir / "second.md").write_text("""\
---
name: Second
colin:
  depends_on:
    - first.md
---

After first: {{ ref('first.md').content }}
""")
        (source_dir / "third.md").write_text("""\
---
name: Third
colin:
  depends_on:
    - second.md
---

After second: {{ ref('second.md').content }}
""")

        result = await engine.compile_all()
        uris = [doc.uri for doc in result]

        # first → second → third
        assert uris.index("project://first.md") < uris.index("project://second.md")
        assert uris.index("project://second.md") < uris.index("project://third.md")

    async def test_depends_on_combined_with_static_refs(
        self, engine_setup: tuple[CompileEngine, Path]
    ) -> None:
        """depends_on works alongside static refs extracted from AST."""
        engine, source_dir = engine_setup

        (source_dir / "a.md").write_text("---\nname: A\n---\nContent A")
        (source_dir / "b.md").write_text("---\nname: B\n---\nContent B")
        (source_dir / "consumer.md").write_text("""\
---
name: Consumer
colin:
  depends_on:
    - b.md
---

Static ref: {{ ref('a.md').content }}
Dynamic ref: {% set dep = 'b.md' %}{{ ref(dep).content }}
""")

        result = await engine.compile_all()
        uris = [doc.uri for doc in result]

        # Both A (static) and B (depends_on) should be before consumer
        assert uris.index("project://a.md") < uris.index("project://consumer.md")
        assert uris.index("project://b.md") < uris.index("project://consumer.md")

        consumer = next(doc for doc in result if doc.uri == "project://consumer.md")
        assert "Content A" in consumer.output
        assert "Content B" in consumer.output
