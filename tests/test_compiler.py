"""Tests for Colin compiler."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from colin.compiler import CompileContext, CompileEngine
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

        assert "other" in context.refs_evaluated

    async def test_ref_returns_ref_result(self, context: CompileContext, tmp_path: Path) -> None:
        source_file = tmp_path / "context" / "doc.md"
        source_file.write_text("---\nname: Doc\ndescription: A doc\n---\nTemplate")
        output_file = tmp_path / "target" / "doc.md"
        output_file.write_text("Compiled content")

        result = await context.ref("doc")

        assert result.name == "Doc"
        assert result.description == "A doc"
        assert result.content == "Compiled content"
        assert str(result) == "Ref('doc')"

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


class TestCompileEngine:
    @pytest.fixture
    def engine_setup(
        self, tmp_path: Path, mock_agent: MagicMock
    ) -> tuple[CompileEngine, Path, Path]:
        source_dir = tmp_path / "context"
        source_dir.mkdir()
        output_dir = tmp_path / "target"
        output_dir.mkdir()

        manifest = Manifest()
        input_plugin = FileInputPlugin(
            model_dirs=[source_dir],
            target_dir=output_dir,
        )

        engine = CompileEngine(
            manifest=manifest,
            input_plugin=input_plugin,
            default_model="test-model",
        )
        return engine, source_dir, output_dir

    async def test_compile_all_empty(self, engine_setup: tuple[CompileEngine, Path, Path]) -> None:
        engine, _, _ = engine_setup
        result = await engine.compile_all()
        assert result == []

    async def test_compile_all_single_document(
        self, engine_setup: tuple[CompileEngine, Path, Path]
    ) -> None:
        engine, source_dir, output_dir = engine_setup
        (source_dir / "test.md").write_text("""\
---
name: Test
---

# Hello World
""")

        result = await engine.compile_all()

        assert len(result) == 1
        assert result[0].uri == "test"
        assert "# Hello World" in result[0].output
        assert (output_dir / "test.md").exists()

    async def test_compile_all_with_ref(
        self, engine_setup: tuple[CompileEngine, Path, Path]
    ) -> None:
        engine, source_dir, output_dir = engine_setup

        (source_dir / "base.md").write_text("""\
---
name: Base
---

Base content here.
""")
        (source_dir / "derived.md").write_text("""\
---
name: Derived
---

Including: {{ ref('base').content }}
""")

        result = await engine.compile_all()

        assert len(result) == 2
        uris = [doc.uri for doc in result]
        assert "base" in uris
        assert "derived" in uris

        derived = next(doc for doc in result if doc.uri == "derived")
        assert "Base content here." in derived.output

    async def test_compile_all_with_llm_block(
        self, engine_setup: tuple[CompileEngine, Path, Path], mock_agent: MagicMock
    ) -> None:
        engine, source_dir, _ = engine_setup

        (source_dir / "llm-test.md").write_text("""\
---
name: LLM Test
---

{% llm %}
Summarize this content.
{% endllm %}
""")

        result = await engine.compile_all()

        assert len(result) == 1
        assert "[TEST LLM RESPONSE]" in result[0].output
        assert len(result[0].llm_calls) == 1

    async def test_compile_all_with_extract_filter(
        self, engine_setup: tuple[CompileEngine, Path, Path], mock_agent: MagicMock
    ) -> None:
        engine, source_dir, _ = engine_setup

        (source_dir / "extract-test.md").write_text("""\
---
name: Extract Test
---

{{ "Some content here" | extract("key points") }}
""")

        result = await engine.compile_all()

        assert len(result) == 1
        assert "[TEST LLM RESPONSE]" in result[0].output

    async def test_compile_all_updates_manifest(
        self, engine_setup: tuple[CompileEngine, Path, Path]
    ) -> None:
        engine, source_dir, _ = engine_setup

        (source_dir / "test.md").write_text("---\nname: Test\n---\nContent")

        await engine.compile_all()

        assert engine.manifest.compiled_at is not None
        assert "test" in engine.manifest.documents

    async def test_compile_uri_single(self, engine_setup: tuple[CompileEngine, Path, Path]) -> None:
        engine, source_dir, output_dir = engine_setup

        (source_dir / "single.md").write_text("""\
---
name: Single
---

Just this one.
""")

        result = await engine.compile_uri("single")

        assert result.uri == "single"
        assert "Just this one." in result.output
        assert (output_dir / "single.md").exists()

    async def test_compile_uri_not_found(
        self, engine_setup: tuple[CompileEngine, Path, Path]
    ) -> None:
        engine, _, _ = engine_setup

        with pytest.raises(FileNotFoundError):
            await engine.compile_uri("nonexistent")

    async def test_compile_order_respects_dependencies(
        self, engine_setup: tuple[CompileEngine, Path, Path]
    ) -> None:
        engine, source_dir, output_dir = engine_setup

        (source_dir / "a.md").write_text("---\nname: A\n---\nA content")
        (source_dir / "b.md").write_text("---\nname: B\n---\nB uses {{ ref('a').content }}")
        (source_dir / "c.md").write_text("---\nname: C\n---\nC uses {{ ref('b').content }}")

        result = await engine.compile_all()
        uris = [doc.uri for doc in result]

        assert uris.index("a") < uris.index("b")
        assert uris.index("b") < uris.index("c")
