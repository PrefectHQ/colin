"""Tests for Colin compiler engine."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from colin.api.project import ProjectConfig
from colin.compiler import CompileEngine
from colin.exceptions import MultipleCompilationErrors
from colin.providers.storage.file import FileStorage


class TestCompileEngine:
    @pytest.fixture
    def engine_setup(
        self, tmp_path: Path, mock_agent: MagicMock
    ) -> tuple[CompileEngine, Path, Path]:
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
            output_path=tmp_path / "output",
            manifest_path=tmp_path / ".colin" / "manifest.json",
        )
        artifact_storage = FileStorage(base_path=compiled_dir)

        engine = CompileEngine(
            config=config,
            artifact_storage=artifact_storage,
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

Including: {{ ref('base.md').content }}
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
        # compile_uri writes to build cache, not target (targeted compilation)
        compiled_dir = engine.config.build_path / "compiled"
        assert (compiled_dir / "single.md").exists()
        # target only gets files after compile_all publishes
        assert not (output_dir / "single.md").exists()

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
        (source_dir / "b.md").write_text("---\nname: B\n---\nB uses {{ ref('a.md').content }}")
        (source_dir / "c.md").write_text("---\nname: C\n---\nC uses {{ ref('b.md').content }}")

        result = await engine.compile_all()
        uris = [doc.uri for doc in result]

        assert uris.index("project://a.md") < uris.index("project://b.md")
        assert uris.index("project://b.md") < uris.index("project://c.md")

    async def test_malformed_json_raises_error(
        self, engine_setup: tuple[CompileEngine, Path, Path]
    ) -> None:
        """Malformed JSON output raises error during compilation."""
        engine, source_dir, _ = engine_setup

        # Malformed JSON - trailing comma
        (source_dir / "bad.md").write_text("""\
---
name: Bad
colin:
  output: json
---

{"foo": "bar",}
""")

        with pytest.raises(MultipleCompilationErrors) as exc_info:
            await engine.compile_all()

        # Underlying error should be JSONDecodeError
        errors = exc_info.value.errors
        assert "project://bad.md" in errors
        assert any(isinstance(e, json.JSONDecodeError) for e in errors["project://bad.md"])

    async def test_ref_returns_rendered_json_content(
        self, engine_setup: tuple[CompileEngine, Path, Path]
    ) -> None:
        """ref() to a JSON document returns rendered JSON, not raw Jinja."""
        engine, source_dir, _ = engine_setup

        # Create a document that outputs JSON
        (source_dir / "config.md").write_text("""\
---
name: Config
colin:
  output: json
---

## host
localhost

## port
```json
5432
```
""")

        # Create a document that refs the JSON config
        (source_dir / "derived.md").write_text("""\
---
name: Derived
---

Config content: {{ ref('config.json').content }}
""")

        result = await engine.compile_all()
        derived = next(doc for doc in result if doc.uri == "project://derived.md")

        # The ref().content should be valid JSON, not raw markdown
        assert '"host": "localhost"' in derived.output
        assert '"port": 5432' in derived.output
        # Should not contain raw markdown headers
        assert "## host" not in derived.output

    async def test_ref_finds_json_output_by_extension(
        self, engine_setup: tuple[CompileEngine, Path, Path]
    ) -> None:
        """ref('config.json') finds the compiled JSON output."""
        engine, source_dir, output_dir = engine_setup

        # Create a JSON-output document
        (source_dir / "config.md").write_text("""\
---
name: Config
colin:
  output: json
---

## key
value
""")

        result = await engine.compile_all()

        # Verify it wrote config.json (not config.md)
        config = next(doc for doc in result if doc.uri == "project://config.md")
        assert config.output_path == "config.json"
        assert (output_dir / "config.json").exists()

    async def test_hash_consistency_between_document_and_manifest(
        self, engine_setup: tuple[CompileEngine, Path, Path]
    ) -> None:
        """CompiledDocument.output_hash matches what's stored in manifest."""
        engine, source_dir, _ = engine_setup

        (source_dir / "test.md").write_text("""\
---
name: Test
colin:
  output: json
---

## key
value
""")

        results = await engine.compile_all()
        doc = results[0]

        # The manifest should have the same output_hash as the CompiledDocument
        manifest_meta = engine.manifest.get_document(doc.uri)
        assert manifest_meta is not None
        assert manifest_meta.output_hash == doc.output_hash

    async def test_frontmatter_change_invalidates_cache(
        self, engine_setup: tuple[CompileEngine, Path, Path]
    ) -> None:
        """Changing frontmatter (e.g., colin.output) triggers recompilation."""
        engine, source_dir, output_dir = engine_setup

        # First compile as markdown
        (source_dir / "config.md").write_text("""\
---
name: Config
---

## key
value
""")
        await engine.compile_all()
        assert (output_dir / "config.md").exists()
        first_meta = engine.manifest.get_document("project://config.md")
        assert first_meta is not None
        first_source_hash = first_meta.source_hash

        # Change output format in frontmatter
        (source_dir / "config.md").write_text("""\
---
name: Config
colin:
  output: json
---

## key
value
""")
        await engine.compile_all()

        # Should have recompiled due to source_hash change
        second_meta = engine.manifest.get_document("project://config.md")
        assert second_meta is not None
        assert second_meta.source_hash != first_source_hash
        # Output path should now be JSON
        assert second_meta.output_path == "config.json"
