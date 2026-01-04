"""Tests for private file functionality."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from colin.api.project import ProjectConfig
from colin.compiler import CompileEngine
from colin.exceptions import MultipleCompilationErrors
from colin.providers.storage.file import FileStorage


@pytest.fixture
def engine_setup(tmp_path: Path, mock_agent: MagicMock) -> tuple[CompileEngine, Path, Path, Path]:
    """Create engine with source, build, and output directories."""
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
    return engine, source_dir, compiled_dir, output_dir


class TestPrivateNamingConvention:
    """Tests for _ prefix marking files as private."""

    async def test_underscore_prefix_marks_file_private(
        self, engine_setup: tuple[CompileEngine, Path, Path, Path]
    ) -> None:
        """Files with _ prefix are private and not published to output."""
        engine, source_dir, compiled_dir, output_dir = engine_setup

        (source_dir / "_helper.md").write_text("---\nname: Helper\n---\nPrivate content")
        (source_dir / "public.md").write_text("---\nname: Public\n---\nPublic content")

        await engine.compile_all()

        # Both files compiled to .colin/compiled/
        assert (compiled_dir / "_helper.md").exists()
        assert (compiled_dir / "public.md").exists()

        # Only public file published to output/
        assert not (output_dir / "_helper.md").exists()
        assert (output_dir / "public.md").exists()

    async def test_underscore_directory_marks_files_private(
        self, engine_setup: tuple[CompileEngine, Path, Path, Path]
    ) -> None:
        """Files in _ prefixed directories are private."""
        engine, source_dir, compiled_dir, output_dir = engine_setup

        partials_dir = source_dir / "_partials"
        partials_dir.mkdir()
        (partials_dir / "intro.md").write_text("---\nname: Intro\n---\nPartial content")
        (source_dir / "main.md").write_text("---\nname: Main\n---\nMain content")

        await engine.compile_all()

        # Both compiled
        assert (compiled_dir / "_partials" / "intro.md").exists()
        assert (compiled_dir / "main.md").exists()

        # Only main published
        assert not (output_dir / "_partials" / "intro.md").exists()
        assert (output_dir / "main.md").exists()

    async def test_nested_underscore_directory_marks_files_private(
        self, engine_setup: tuple[CompileEngine, Path, Path, Path]
    ) -> None:
        """Files under nested _ prefixed directories are private."""
        engine, source_dir, compiled_dir, output_dir = engine_setup

        nested_dir = source_dir / "chapters" / "_drafts"
        nested_dir.mkdir(parents=True)
        (nested_dir / "draft.md").write_text("---\nname: Draft\n---\nDraft content")

        await engine.compile_all()

        assert (compiled_dir / "chapters" / "_drafts" / "draft.md").exists()
        assert not (output_dir / "chapters" / "_drafts" / "draft.md").exists()

    async def test_manifest_tracks_private_status(
        self, engine_setup: tuple[CompileEngine, Path, Path, Path]
    ) -> None:
        """Manifest correctly records private status."""
        engine, source_dir, _, _ = engine_setup

        (source_dir / "_private.md").write_text("---\nname: Private\n---\nContent")
        (source_dir / "public.md").write_text("---\nname: Public\n---\nContent")

        await engine.compile_all()

        private_meta = engine.manifest.get_document("project://_private.md")
        public_meta = engine.manifest.get_document("project://public.md")

        assert private_meta is not None
        assert private_meta.is_private is True

        assert public_meta is not None
        assert public_meta.is_private is False


class TestPrivateFrontmatterOverride:
    """Tests for frontmatter overriding naming convention."""

    async def test_frontmatter_private_true_overrides_public_name(
        self, engine_setup: tuple[CompileEngine, Path, Path, Path]
    ) -> None:
        """Frontmatter colin.private: true makes a normally public file private."""
        engine, source_dir, compiled_dir, output_dir = engine_setup

        (source_dir / "secret.md").write_text("""\
---
name: Secret
colin:
  private: true
---

Secret content
""")

        await engine.compile_all()

        # Compiled but not published
        assert (compiled_dir / "secret.md").exists()
        assert not (output_dir / "secret.md").exists()

        meta = engine.manifest.get_document("project://secret.md")
        assert meta is not None
        assert meta.is_private is True

    async def test_frontmatter_private_false_overrides_underscore_prefix(
        self, engine_setup: tuple[CompileEngine, Path, Path, Path]
    ) -> None:
        """Frontmatter colin.private: false makes a _ prefixed file public."""
        engine, source_dir, compiled_dir, output_dir = engine_setup

        (source_dir / "_actually_public.md").write_text("""\
---
name: Actually Public
colin:
  private: false
---

Public content despite underscore
""")

        await engine.compile_all()

        # Both compiled and published
        assert (compiled_dir / "_actually_public.md").exists()
        assert (output_dir / "_actually_public.md").exists()

        meta = engine.manifest.get_document("project://_actually_public.md")
        assert meta is not None
        assert meta.is_private is False


class TestPrivateRefBehavior:
    """Tests for ref() behavior with private files."""

    async def test_provider_path_raises_on_private_files(
        self, engine_setup: tuple[CompileEngine, Path, Path, Path]
    ) -> None:
        """Direct provider access: path/relative_path raise on private files."""
        engine, source_dir, _, _ = engine_setup

        (source_dir / "_helper.md").write_text("""\
---
name: Helper
---

Helper content.
""")

        await engine.compile_all()

        # Get the resource from the provider directly
        resource = await engine._project_provider.get("_helper.md")

        # Content works
        assert "Helper content" in resource.content

        # Path raises
        with pytest.raises(ValueError, match="private file"):
            _ = resource.path

        # relative_path also raises
        with pytest.raises(ValueError, match="private file"):
            _ = resource.relative_path

    async def test_ref_content_works_on_private_files(
        self, engine_setup: tuple[CompileEngine, Path, Path, Path]
    ) -> None:
        """ref().content works for private files."""
        engine, source_dir, _, output_dir = engine_setup

        (source_dir / "_data.md").write_text("---\nname: Data\n---\nSecret data")
        (source_dir / "consumer.md").write_text("""\
---
name: Consumer
---

Data: {{ ref('_data.md').content }}
""")

        result = await engine.compile_all()

        consumer = next(doc for doc in result if doc.uri == "project://consumer.md")
        assert "Secret data" in consumer.output
        assert (output_dir / "consumer.md").exists()

    async def test_ref_path_raises_on_private_files(
        self, engine_setup: tuple[CompileEngine, Path, Path, Path]
    ) -> None:
        """ref().path raises ValueError for private files."""
        engine, source_dir, _, _ = engine_setup

        (source_dir / "_private.md").write_text("---\nname: Private\n---\nContent")
        (source_dir / "linker.md").write_text("""\
---
name: Linker
---

Link: {{ ref('_private.md').path }}
""")

        with pytest.raises(MultipleCompilationErrors) as exc_info:
            await engine.compile_all()

        # Check that the underlying error is about private file path access
        errors = exc_info.value.errors
        assert "project://linker.md" in errors
        error_msgs = [str(e) for e in errors["project://linker.md"]]
        assert any("Cannot get path for private file" in msg for msg in error_msgs)

    async def test_ref_relative_path_raises_on_private_files(
        self, engine_setup: tuple[CompileEngine, Path, Path, Path]
    ) -> None:
        """ref().relative_path raises ValueError for private files."""
        engine, source_dir, _, _ = engine_setup

        (source_dir / "_private.md").write_text("---\nname: Private\n---\nContent")
        (source_dir / "linker.md").write_text("""\
---
name: Linker
---

Relative: {{ ref('_private.md').relative_path }}
""")

        with pytest.raises(MultipleCompilationErrors) as exc_info:
            await engine.compile_all()

        # Check that the underlying error is about private file relative_path access
        errors = exc_info.value.errors
        assert "project://linker.md" in errors
        error_msgs = [str(e) for e in errors["project://linker.md"]]
        assert any("Cannot get relative_path for private file" in msg for msg in error_msgs)


class TestPrivateNonMarkdownOutputs:
    """Tests for privacy with JSON/YAML outputs referenced by output filename."""

    async def test_private_json_output_path_raises(
        self, engine_setup: tuple[CompileEngine, Path, Path, Path]
    ) -> None:
        """ref('_config.json').path raises for private JSON outputs."""
        engine, source_dir, _, _ = engine_setup

        (source_dir / "_config.md").write_text("""\
---
name: Config
colin:
  output: json
---

## key
value
""")
        (source_dir / "consumer.md").write_text("""\
---
name: Consumer
---

Path: {{ ref('_config.json').path }}
""")

        with pytest.raises(MultipleCompilationErrors) as exc_info:
            await engine.compile_all()

        errors = exc_info.value.errors
        assert "project://consumer.md" in errors
        error_msgs = [str(e) for e in errors["project://consumer.md"]]
        assert any("Cannot get path for private file" in msg for msg in error_msgs)

    async def test_private_json_content_works(
        self, engine_setup: tuple[CompileEngine, Path, Path, Path]
    ) -> None:
        """ref('_config.json').content works for private JSON outputs."""
        engine, source_dir, _, output_dir = engine_setup

        (source_dir / "_config.md").write_text("""\
---
name: Config
colin:
  output: json
---

## key
value
""")
        (source_dir / "consumer.md").write_text("""\
---
name: Consumer
---

Content: {{ ref('_config.json').content }}
""")

        result = await engine.compile_all()

        consumer = next(doc for doc in result if doc.uri == "project://consumer.md")
        assert '"key": "value"' in consumer.output
        assert (output_dir / "consumer.md").exists()
        # Private JSON should NOT be in target
        assert not (output_dir / "_config.json").exists()

    async def test_private_yaml_output_path_raises(
        self, engine_setup: tuple[CompileEngine, Path, Path, Path]
    ) -> None:
        """ref('_config.yaml').path raises for private YAML outputs."""
        engine, source_dir, _, _ = engine_setup

        (source_dir / "_config.md").write_text("""\
---
name: Config
colin:
  output: yaml
---

## key
value
""")
        (source_dir / "consumer.md").write_text("""\
---
name: Consumer
---

Path: {{ ref('_config.yaml').path }}
""")

        with pytest.raises(MultipleCompilationErrors) as exc_info:
            await engine.compile_all()

        errors = exc_info.value.errors
        assert "project://consumer.md" in errors
        error_msgs = [str(e) for e in errors["project://consumer.md"]]
        assert any("Cannot get path for private file" in msg for msg in error_msgs)

    async def test_ref_json_output_finds_correct_metadata(
        self, engine_setup: tuple[CompileEngine, Path, Path, Path]
    ) -> None:
        """ref('config.json') finds manifest metadata via output_path lookup."""
        engine, source_dir, compiled_dir, output_dir = engine_setup

        (source_dir / "config.md").write_text("""\
---
name: Config
colin:
  output: json
---

## host
localhost
""")

        await engine.compile_all()

        # Verify manifest has correct output_path
        doc_meta = engine.manifest.get_document("project://config.md")
        assert doc_meta is not None
        assert doc_meta.output_path == "config.json"

        # Verify lookup by output_path works
        by_output = engine.manifest.get_document_by_output_path("config.json")
        assert by_output is not None
        assert by_output.uri == "project://config.md"

        # Verify output exists in correct location
        assert (output_dir / "config.json").exists()
        assert (compiled_dir / "config.json").exists()


class TestParentDirectoryDoesNotAffectPrivacy:
    """Tests that parent directories outside models root don't affect privacy."""

    async def test_underscore_parent_outside_models_does_not_make_private(
        self, tmp_path: Path, mock_agent: MagicMock
    ) -> None:
        """Parent directories outside models root don't affect privacy detection."""
        # Create project in a directory with underscore prefix
        project_root = tmp_path / "_my_project"
        project_root.mkdir()

        source_dir = project_root / "models"
        source_dir.mkdir()
        output_dir = project_root / "output"
        output_dir.mkdir()
        build_dir = project_root / ".colin"
        build_dir.mkdir()
        compiled_dir = build_dir / "compiled"
        compiled_dir.mkdir()

        config = ProjectConfig(
            name="test-project",
            project_root=project_root,
            model_path=source_dir,
            output_path=output_dir,
            manifest_path=build_dir / "manifest.json",
        )
        artifact_storage = FileStorage(base_path=compiled_dir)
        engine = CompileEngine(config=config, artifact_storage=artifact_storage)

        # File inside models root without underscore should be public
        (source_dir / "public.md").write_text("---\nname: Public\n---\nContent")

        await engine.compile_all()

        # File should be published even though project is in _my_project/
        assert (output_dir / "public.md").exists()

        meta = engine.manifest.get_document("project://public.md")
        assert meta is not None
        assert meta.is_private is False
