"""Tests for Colin compiler context."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from colin.compiler import CompileContext
from colin.exceptions import RefNotFoundError
from colin.models import DocumentMeta, LLMCall, Manifest
from colin.plugins.inputs.file import FileInputPlugin

if TYPE_CHECKING:
    pass


class TestCompileContext:
    @pytest.fixture
    def context(self, tmp_path: Path, mock_agent: MagicMock) -> CompileContext:
        source_dir = tmp_path / "context"
        source_dir.mkdir()
        output_dir = tmp_path / "target"
        output_dir.mkdir()

        manifest = Manifest()
        input_plugin = FileInputPlugin(
            model_dirs=[source_dir],
            target_dir=output_dir,
        )

        return CompileContext(
            manifest=manifest,
            document_uri="test-doc",
            default_model="test-model",
            input_plugin=input_plugin,
        )

    async def test_ref_tracks_dependency(self, context: CompileContext, tmp_path: Path) -> None:
        source_file = tmp_path / "context" / "other.md"
        source_file.write_text("---\nname: Other\n---\nContent")
        output_file = tmp_path / "target" / "other.md"
        output_file.write_text("Compiled other")

        await context.ref("other")

        assert "project://other.md" in context.refs_evaluated

    async def test_ref_returns_ref_result(self, context: CompileContext, tmp_path: Path) -> None:
        source_file = tmp_path / "context" / "doc.md"
        source_file.write_text("---\nname: Doc\ndescription: A doc\n---\nTemplate")
        output_file = tmp_path / "target" / "doc.md"
        output_file.write_text("Compiled content")

        result = await context.ref("doc")

        assert result.name == "Doc"
        assert result.description == "A doc"
        assert result.content == "Compiled content"
        assert str(result) == "Ref('project://doc.md')"

    async def test_ref_not_found(self, context: CompileContext) -> None:
        with pytest.raises(RefNotFoundError):
            await context.ref("nonexistent")

    async def test_extract_calls_llm(self, context: CompileContext, mock_agent: MagicMock) -> None:
        result = await context.extract("Some content", "Extract names")

        assert result is not None
        assert result == "[TEST LLM RESPONSE]"
        mock_agent.assert_called()

    async def test_extract_records_call(
        self, context: CompileContext, mock_agent: MagicMock
    ) -> None:
        await context.extract("Content", "Extract")

        assert len(context.llm_calls) == 1

    async def test_extract_with_manual_id(
        self, context: CompileContext, mock_agent: MagicMock
    ) -> None:
        await context.extract("Content", "Extract", call_id="my-id")

        assert "my-id" in context.llm_calls

    async def test_extract_auto_id_is_deterministic(
        self, context: CompileContext, mock_agent: MagicMock
    ) -> None:
        await context.extract("Content", "Extract")
        call_id = list(context.llm_calls.keys())[0]

        assert call_id.startswith("auto:")

    async def test_extract_caches_on_same_input(
        self, context: CompileContext, tmp_path: Path, mock_agent: MagicMock
    ) -> None:
        context.manifest.set_document(
            "test-doc",
            DocumentMeta(
                uri="test-doc",
                source_path=str(tmp_path / "test.md"),
                source_hash="abc",
                llm_calls={
                    "auto:1234567890123456": LLMCall(
                        call_id="auto:1234567890123456",
                        input_hash=context._hash("Content"),
                        output_hash="out",
                        output="Cached result",
                        model="test-model",
                    )
                },
            ),
        )

        result = await context.extract("Content", "Extract", call_id="auto:1234567890123456")
        assert result == "Cached result"

    async def test_call_llm_block(self, context: CompileContext, mock_agent: MagicMock) -> None:
        result = await context.call_llm_block(
            body="Test prompt",
            model=None,
            call_id=None,
        )

        assert result is not None
        assert result == "[TEST LLM RESPONSE]"

    async def test_call_llm_block_records_call(
        self, context: CompileContext, mock_agent: MagicMock
    ) -> None:
        await context.call_llm_block(
            body="Test prompt",
            model=None,
            call_id="block-1",
        )

        assert "block-1" in context.llm_calls
