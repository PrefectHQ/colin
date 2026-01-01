"""Tests for Colin compiler context."""

from __future__ import annotations

from pathlib import Path

import pytest

from colin.compiler import CompileContext
from colin.exceptions import RefNotFoundError
from colin.models import Address, LLMCall, Manifest
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

        # Check that an Address with the right payload was tracked
        assert len(context.refs_evaluated) == 1
        addr = context.refs_evaluated[0]
        assert addr["provider"] == "project"
        assert addr["payload"]["path"] == "other.md"

    async def test_ref_returns_addressable(self, context: CompileContext, tmp_path: Path) -> None:
        source_file = tmp_path / "context" / "doc.md"
        source_file.write_text("---\nname: Doc\ndescription: A doc\n---\nTemplate")
        output_file = tmp_path / "target" / "doc.md"
        output_file.write_text("Compiled content")

        result = await context.ref("doc")

        # Returns Addressable (ProjectResource) with content
        assert result.content == "Compiled content"
        # Address has structured payload for re-fetching
        addr = result.address()
        assert addr["provider"] == "project"
        assert addr["payload"]["path"] == "doc.md"
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

    async def test_track_ref_adds_to_refs_evaluated(self, context: CompileContext) -> None:
        """Test that track_ref adds Address to refs_evaluated without fetching."""
        addr = Address(provider="test", instance="", payload={"uri": "some://uri"})
        context.track_ref(addr)

        assert len(context.refs_evaluated) == 1
        assert context.refs_evaluated[0] == addr

    async def test_track_ref_deduplicates(self, context: CompileContext) -> None:
        """Test that track_ref doesn't add duplicates."""
        addr = Address(provider="test", instance="", payload={"uri": "some://uri"})
        context.track_ref(addr)
        context.track_ref(addr)

        assert len(context.refs_evaluated) == 1
