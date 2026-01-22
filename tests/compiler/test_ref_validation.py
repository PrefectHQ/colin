"""Tests for ref() validation - strict compilation model.

By default, ref() requires the target to be compiled in the current run.
Use allow_stale=True to accept stale data from previous compilations.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from colin.api.project import ProjectConfig
from colin.compiler import CompileContext, CompileEngine
from colin.exceptions import CyclicDependencyError, RefNotCompiledError
from colin.models import CompiledDocument, Frontmatter, Manifest
from colin.providers.project import ProjectProvider
from colin.providers.storage.file import FileStorage


class TestStrictRefValidation:
    """Tests for strict ref validation - targets must be compiled first."""

    @pytest.fixture
    def project_setup(
        self, tmp_path: Path, mock_agent: MagicMock
    ) -> tuple[CompileContext, Path, Path]:
        """Set up a project with models directory."""
        source_dir = tmp_path / "models"
        source_dir.mkdir()
        output_dir = tmp_path / "target"
        output_dir.mkdir()

        manifest = Manifest()
        project_provider = ProjectProvider(base_path=output_dir)
        config = ProjectConfig(
            name="test",
            project_root=tmp_path,
            model_path=source_dir,
            output_path=output_dir,
            manifest_path=tmp_path / ".colin" / "manifest.json",
        )

        context = CompileContext(
            manifest=manifest,
            document_uri="test-doc",
            project_provider=project_provider,
            config=config,
        )
        return context, source_dir, output_dir

    async def test_ref_to_compiled_document_succeeds(
        self, project_setup: tuple[CompileContext, Path, Path]
    ) -> None:
        """ref() succeeds when target is in compiled_outputs."""
        context, source_dir, output_dir = project_setup

        # Add a compiled document to the context
        context.compiled_outputs["greeting.md"] = CompiledDocument(
            uri="project://greeting.md",
            frontmatter=Frontmatter(),
            output="Hello, world!",
            source_hash="abc123",
            output_hash="def456",
            output_path="greeting.md",
        )

        result = await context.ref("greeting.md")
        assert result is not None
        assert result.content == "Hello, world!"

    async def test_ref_to_uncompiled_document_raises_error(
        self, project_setup: tuple[CompileContext, Path, Path]
    ) -> None:
        """ref() raises RefNotCompiledError when target not compiled."""
        context, source_dir, output_dir = project_setup

        # No documents compiled - should fail
        with pytest.raises(RefNotCompiledError) as exc_info:
            await context.ref("missing.md")

        err = exc_info.value
        assert err.target == "missing.md"
        assert "depends_on" in str(err)  # Error suggests solution
        assert "allow_stale" in str(err)  # Error mentions escape hatch

    async def test_ref_allow_stale_reads_from_storage(
        self, project_setup: tuple[CompileContext, Path, Path]
    ) -> None:
        """ref(allow_stale=True) reads from storage when not compiled."""
        context, source_dir, output_dir = project_setup

        # Write file to storage (simulating previous compilation)
        (output_dir / "stale.md").write_text("Stale content from previous run")

        result = await context.ref("stale.md", allow_stale=True)
        assert result is not None
        assert result.content == "Stale content from previous run"

    async def test_ref_allow_stale_returns_none_when_never_compiled(
        self, project_setup: tuple[CompileContext, Path, Path]
    ) -> None:
        """ref(allow_stale=True) returns None when target has never been compiled."""
        context, source_dir, output_dir = project_setup

        # No file on disk
        result = await context.ref("never-existed.md", allow_stale=True)
        assert result is None

    async def test_ref_dependency_tracked_from_compiled_outputs(
        self, project_setup: tuple[CompileContext, Path, Path]
    ) -> None:
        """Dependencies are tracked when reading from compiled_outputs."""
        context, source_dir, output_dir = project_setup

        context.compiled_outputs["dep.md"] = CompiledDocument(
            uri="project://dep.md",
            frontmatter=Frontmatter(),
            output="Dependency content",
            source_hash="abc",
            output_hash="def",
            output_path="dep.md",
        )

        await context.ref("dep.md")

        assert len(context.refs) == 1
        assert context.refs[0].args["path"] == "dep.md"

    async def test_ref_dependency_tracked_with_allow_stale(
        self, project_setup: tuple[CompileContext, Path, Path]
    ) -> None:
        """Dependencies are tracked when using allow_stale with existing file."""
        context, source_dir, output_dir = project_setup

        (output_dir / "stale.md").write_text("Stale content")

        await context.ref("stale.md", allow_stale=True)

        assert len(context.refs) == 1
        assert context.refs[0].args["path"] == "stale.md"

    async def test_ref_dependency_tracked_when_none_returned(
        self, project_setup: tuple[CompileContext, Path, Path]
    ) -> None:
        """Dependencies ARE tracked when allow_stale returns None.

        This ensures the document rebuilds when the missing target is added.
        """
        context, source_dir, output_dir = project_setup

        result = await context.ref("never-existed.md", allow_stale=True)
        assert result is None

        # Dependency is tracked with __missing__ version
        assert len(context.refs) == 1
        assert context.refs[0].args["path"] == "never-existed.md"
        assert context.ref_versions[context.refs[0].key()] == "__missing__"

    async def test_ref_not_compiled_error_not_recorded_as_dependency(
        self, project_setup: tuple[CompileContext, Path, Path]
    ) -> None:
        """RefNotCompiledError should not record the ref as a dependency."""
        context, source_dir, output_dir = project_setup

        with pytest.raises(RefNotCompiledError):
            await context.ref("missing.md")

        assert len(context.refs) == 0


class TestPathTraversalPrevention:
    """Tests that path traversal attempts are caught.

    With strict compilation model, path traversal refs fail with RefNotCompiledError
    (since the target is never in compiled_outputs).
    """

    @pytest.fixture
    def project_setup(
        self, tmp_path: Path, mock_agent: MagicMock
    ) -> tuple[CompileContext, Path, Path]:
        """Set up a project with models directory."""
        source_dir = tmp_path / "project" / "models"
        source_dir.mkdir(parents=True)
        output_dir = tmp_path / "project" / "target"
        output_dir.mkdir()

        # Create a file OUTSIDE the project
        outside_file = tmp_path / "secret.md"
        outside_file.write_text("---\nname: Secret\n---\nSecret content")

        manifest = Manifest()
        project_provider = ProjectProvider(base_path=output_dir)
        config = ProjectConfig(
            name="test",
            project_root=tmp_path / "project",
            model_path=source_dir,
            output_path=output_dir,
            manifest_path=tmp_path / "project" / ".colin" / "manifest.json",
        )

        context = CompileContext(
            manifest=manifest,
            document_uri="test-doc",
            project_provider=project_provider,
            config=config,
        )
        return context, source_dir, output_dir

    async def test_path_traversal_outside_project_raises(
        self, project_setup: tuple[CompileContext, Path, Path]
    ) -> None:
        """Schemaless refs with ../ that escape project should fail."""
        context, source_dir, output_dir = project_setup

        # Attempt to reference file outside project via path traversal
        # With strict model, this fails because ../secret.md is not compiled
        with pytest.raises(RefNotCompiledError) as exc_info:
            await context.ref("../secret.md")

        assert "../secret.md" in str(exc_info.value)

    async def test_deep_path_traversal_raises(
        self, project_setup: tuple[CompileContext, Path, Path]
    ) -> None:
        """Deep path traversal attempts should fail."""
        context, source_dir, output_dir = project_setup

        with pytest.raises(RefNotCompiledError):
            await context.ref("../../../../../../etc/passwd")


class TestAllowStaleCycleBreaking:
    """Tests for allow_stale=True breaking dependency cycles."""

    @pytest.fixture
    def engine_setup(self, tmp_path: Path, mock_agent: MagicMock) -> tuple[CompileEngine, Path]:
        source_dir = tmp_path / "models"
        source_dir.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
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

    async def test_cycle_without_allow_stale_raises_error(
        self, engine_setup: tuple[CompileEngine, Path]
    ) -> None:
        """Cycles without allow_stale raise CyclicDependencyError."""
        engine, source_dir = engine_setup

        # Create a cycle: A refs B, B refs A
        (source_dir / "a.md").write_text("""\
---
name: A
---
From B: {{ ref('b.md').content }}
""")
        (source_dir / "b.md").write_text("""\
---
name: B
---
From A: {{ ref('a.md').content }}
""")

        with pytest.raises(CyclicDependencyError) as exc_info:
            await engine.compile_all()

        # Error should show the cycle path
        assert "a.md" in str(exc_info.value) or "b.md" in str(exc_info.value)

    async def test_cycle_with_allow_stale_compiles_successfully(
        self, engine_setup: tuple[CompileEngine, Path]
    ) -> None:
        """allow_stale=True breaks cycles by removing ordering edge."""
        engine, source_dir = engine_setup

        # Create a cycle where one side uses allow_stale
        # A refs B normally, B refs A with allow_stale=True
        (source_dir / "a.md").write_text("""\
---
name: A
---
From B: {{ ref('b.md').content }}
""")
        (source_dir / "b.md").write_text("""\
---
name: B
---
From A: {{ ref('a.md', allow_stale=True).content if ref('a.md', allow_stale=True) else 'no A yet' }}
""")

        # Should compile without CyclicDependencyError
        result = await engine.compile_all()
        assert len(result) == 2

        # B compiles first (no ordering edge from B to A)
        # A compiles second and can ref B
        a_doc = next(d for d in result if d.uri == "project://a.md")
        assert "From B:" in a_doc.output

    async def test_cycle_with_allow_stale_on_both_sides(
        self, engine_setup: tuple[CompileEngine, Path]
    ) -> None:
        """Both sides using allow_stale means no cycle in graph."""
        engine, source_dir = engine_setup

        # Both sides use allow_stale - no ordering edges, no cycle
        (source_dir / "a.md").write_text("""\
---
name: A
---
{% set b = ref('b.md', allow_stale=True) %}
From B: {{ b.content if b else 'no B' }}
""")
        (source_dir / "b.md").write_text("""\
---
name: B
---
{% set a = ref('a.md', allow_stale=True) %}
From A: {{ a.content if a else 'no A' }}
""")

        # Should compile - order is arbitrary, first one sees None
        result = await engine.compile_all()
        assert len(result) == 2

    async def test_three_way_cycle_broken_by_allow_stale(
        self, engine_setup: tuple[CompileEngine, Path]
    ) -> None:
        """allow_stale can break longer cycles."""
        engine, source_dir = engine_setup

        # Create cycle: A → B → C → A
        # Use allow_stale on C → A to break it
        (source_dir / "a.md").write_text("""\
---
name: A
---
From B: {{ ref('b.md').content }}
""")
        (source_dir / "b.md").write_text("""\
---
name: B
---
From C: {{ ref('c.md').content }}
""")
        (source_dir / "c.md").write_text("""\
---
name: C
---
{% set a = ref('a.md', allow_stale=True) %}
From A: {{ a.content if a else 'no A yet' }}
""")

        # Should compile: C first (no edge to A), then A, then B
        result = await engine.compile_all()
        assert len(result) == 3

    async def test_allow_stale_missing_target_triggers_rebuild_when_added(
        self, engine_setup: tuple[CompileEngine, Path]
    ) -> None:
        """allow_stale refs to missing targets rebuild when target is added."""
        engine, source_dir = engine_setup

        # A refs B with allow_stale and depends_on to ensure ordering
        # depends_on is needed because allow_stale removes the ordering edge
        (source_dir / "a.md").write_text("""\
---
name: A
colin:
  depends_on:
    - b.md
---
{% set b = ref('b.md', allow_stale=True) %}
From B: {{ b.content if b else 'not available' }}
""")

        # First compile - B missing, A sees None
        result1 = await engine.compile_all()
        assert len(result1) == 1
        a_doc = result1[0]
        assert "not available" in a_doc.output

        # Save manifest
        engine.config.manifest_path.write_text(
            engine.manifest.model_dump_json(indent=2), encoding="utf-8"
        )

        # Now add B
        (source_dir / "b.md").write_text("---\nname: B\n---\nContent from B!")

        # Create new engine (simulating new compile run)
        engine2 = CompileEngine(
            config=engine.config,
            artifact_storage=FileStorage(base_path=engine.config.build_path / "compiled"),
        )

        # Second compile - A should rebuild to pick up B
        result2 = await engine2.compile_all()
        # Both A and B should be in results (B is new, A is stale due to ref change)
        assert len(result2) == 2
        a_doc2 = next(d for d in result2 if d.uri == "project://a.md")
        assert "Content from B!" in a_doc2.output
