"""Tests for Colin compiler context."""

from __future__ import annotations

from pathlib import Path

import pytest

from colin.compiler import CompileContext
from colin.exceptions import RefNotFoundError
from colin.models import LLMCall, Manifest, Ref
from colin.providers.project import ProjectProvider


class TestCompileContext:
    @pytest.fixture
    def context(self, tmp_path: Path) -> CompileContext:
        source_dir = tmp_path / "context"
        source_dir.mkdir()
        output_dir = tmp_path / "target"
        output_dir.mkdir()

        manifest = Manifest()
        project_provider = ProjectProvider(base_path=output_dir)

        return CompileContext(
            manifest=manifest,
            document_uri="test-doc",
            project_provider=project_provider,
        )

    async def test_ref_tracks_dependency(self, context: CompileContext, tmp_path: Path) -> None:
        source_file = tmp_path / "context" / "other.md"
        source_file.write_text("---\nname: Other\n---\nContent")
        output_file = tmp_path / "target" / "other.md"
        output_file.write_text("Compiled other")

        await context.ref("other")

        # Check that a Ref with the right args was tracked
        assert len(context.refs) == 1
        ref = context.refs[0]
        assert ref.provider == "project"
        assert ref.args["path"] == "other.md"
        # Version should be tracked
        assert ref.key() in context.ref_versions

    async def test_ref_returns_resource(self, context: CompileContext, tmp_path: Path) -> None:
        source_file = tmp_path / "context" / "doc.md"
        source_file.write_text("---\nname: Doc\ndescription: A doc\n---\nTemplate")
        output_file = tmp_path / "target" / "doc.md"
        output_file.write_text("Compiled content")

        result = await context.ref("doc")

        # Returns Resource (ProjectResource) with content
        assert result.content == "Compiled content"
        # ref() returns Ref for re-fetching
        ref = result.ref()
        assert ref.provider == "project"
        assert ref.args["path"] == "doc.md"
        # __str__ returns content for template use
        assert str(result) == "Compiled content"

    async def test_ref_not_found(self, context: CompileContext) -> None:
        with pytest.raises(RefNotFoundError):
            await context.ref("nonexistent")

    async def test_add_llm_call_records_call(self, context: CompileContext) -> None:
        """Test that add_llm_call properly records an LLM call."""
        llm_call = LLMCall(
            call_id="test-call",
            input_hash="abc123",
            output_hash="def456",
            output="test output",
            model="test-model",
            cost_usd=0.001,
        )

        context.add_llm_call(llm_call)

        assert "test-call" in context.llm_calls
        assert context.llm_calls["test-call"].output == "test output"
        assert context.total_cost == 0.001

    async def test_add_llm_call_accumulates_cost(self, context: CompileContext) -> None:
        """Test that multiple LLM calls accumulate cost."""
        context.add_llm_call(
            LLMCall(
                call_id="call-1",
                input_hash="a",
                output_hash="b",
                output="out1",
                model="m",
                cost_usd=0.01,
            )
        )
        context.add_llm_call(
            LLMCall(
                call_id="call-2",
                input_hash="c",
                output_hash="d",
                output="out2",
                model="m",
                cost_usd=0.02,
            )
        )

        assert len(context.llm_calls) == 2
        assert context.total_cost == pytest.approx(0.03)

    async def test_track_adds_ref_and_version(self, context: CompileContext) -> None:
        """Test that track adds Ref and version to tracking lists."""
        ref = Ref(provider="test", connection="", method="get", args={"uri": "some://uri"})
        context.track(ref, "version-1")

        assert len(context.refs) == 1
        assert context.refs[0] == ref
        assert context.ref_versions[ref.key()] == "version-1"

    async def test_track_deduplicates(self, context: CompileContext) -> None:
        """Test that track doesn't add duplicates."""
        ref = Ref(provider="test", connection="", method="get", args={"uri": "some://uri"})
        context.track(ref, "version-1")
        context.track(ref, "version-2")  # Same ref, different version

        assert len(context.refs) == 1
        # First version wins (existing behavior)
        assert context.ref_versions[ref.key()] == "version-1"


class TestNormalizePath:
    """Tests for _normalize_path extension handling."""

    @pytest.fixture
    def context(self, tmp_path: Path) -> CompileContext:
        output_dir = tmp_path / "target"
        output_dir.mkdir()
        manifest = Manifest()
        project_provider = ProjectProvider(base_path=output_dir)
        return CompileContext(
            manifest=manifest,
            document_uri="test-doc",
            project_provider=project_provider,
        )

    def test_adds_md_extension_when_no_extension(self, context: CompileContext) -> None:
        """ref('config') should default to config.md."""
        assert context._normalize_path("config") == "config.md"

    def test_preserves_json_extension(self, context: CompileContext) -> None:
        """ref('config.json') should preserve .json extension."""
        assert context._normalize_path("config.json") == "config.json"

    def test_preserves_yaml_extension(self, context: CompileContext) -> None:
        """ref('config.yaml') should preserve .yaml extension."""
        assert context._normalize_path("config.yaml") == "config.yaml"

    def test_preserves_md_extension(self, context: CompileContext) -> None:
        """ref('config.md') should preserve .md extension."""
        assert context._normalize_path("config.md") == "config.md"

    def test_handles_subdirectory_paths(self, context: CompileContext) -> None:
        """ref('subdir/config') should add .md to the filename only."""
        assert context._normalize_path("subdir/config") == "subdir/config.md"

    def test_preserves_extension_in_subdirectory(self, context: CompileContext) -> None:
        """ref('subdir/config.json') should preserve extension."""
        assert context._normalize_path("subdir/config.json") == "subdir/config.json"
