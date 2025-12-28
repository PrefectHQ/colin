"""Tests for Colin compiler engine."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from colin.compiler import CompileEngine
from colin.models import Manifest
from colin.plugins.inputs.file import FileInputPlugin


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
        assert result[0].uri == "project://test.md"
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
        assert "project://base.md" in uris
        assert "project://derived.md" in uris

        derived = next(doc for doc in result if doc.uri == "project://derived.md")
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
        assert "project://test.md" in engine.manifest.documents

    async def test_compile_uri_single(self, engine_setup: tuple[CompileEngine, Path, Path]) -> None:
        engine, source_dir, output_dir = engine_setup

        (source_dir / "single.md").write_text("""\
---
name: Single
---

Just this one.
""")

        result = await engine.compile_uri("project://single.md")

        assert result.uri == "project://single.md"
        assert "Just this one." in result.output
        assert (output_dir / "single.md").exists()

    async def test_compile_uri_not_found(
        self, engine_setup: tuple[CompileEngine, Path, Path]
    ) -> None:
        engine, _, _ = engine_setup

        with pytest.raises(FileNotFoundError):
            await engine.compile_uri("project://nonexistent.md")

    async def test_compile_order_respects_dependencies(
        self, engine_setup: tuple[CompileEngine, Path, Path]
    ) -> None:
        engine, source_dir, output_dir = engine_setup

        (source_dir / "a.md").write_text("---\nname: A\n---\nA content")
        (source_dir / "b.md").write_text("---\nname: B\n---\nB uses {{ ref('a').content }}")
        (source_dir / "c.md").write_text("---\nname: C\n---\nC uses {{ ref('b').content }}")

        result = await engine.compile_all()
        uris = [doc.uri for doc in result]

        assert uris.index("project://a.md") < uris.index("project://b.md")
        assert uris.index("project://b.md") < uris.index("project://c.md")
