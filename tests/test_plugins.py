"""Tests for Colin plugins."""

from __future__ import annotations

from pathlib import Path

import pytest

from colin.plugins.inputs.file import FileInputPlugin


class TestFileInputPlugin:
    @pytest.fixture
    def plugin(self, tmp_path: Path) -> FileInputPlugin:
        model_dir = tmp_path / "models"
        model_dir.mkdir()
        target_dir = tmp_path / "target"
        target_dir.mkdir()
        return FileInputPlugin(
            model_dirs=[model_dir],
            target_dir=target_dir,
        )

    def test_uri_to_model_path_found(self, plugin: FileInputPlugin) -> None:
        model_file = plugin.model_dirs[0] / "test.md"
        model_file.write_text("content")

        path = plugin.uri_to_model_path("test")
        assert path == model_file

    def test_uri_to_model_path_not_found(self, plugin: FileInputPlugin) -> None:
        path = plugin.uri_to_model_path("nonexistent")
        assert path is None

    def test_uri_to_model_path_nested(self, plugin: FileInputPlugin) -> None:
        nested_dir = plugin.model_dirs[0] / "sub"
        nested_dir.mkdir()
        model_file = nested_dir / "test.md"
        model_file.write_text("content")

        path = plugin.uri_to_model_path("sub/test")
        assert path == model_file

    def test_uri_to_target_path(self, plugin: FileInputPlugin) -> None:
        path = plugin.uri_to_target_path("test")
        assert path == plugin.target_dir / "test.md"

    def test_uri_to_target_path_nested(self, plugin: FileInputPlugin) -> None:
        path = plugin.uri_to_target_path("sub/test")
        assert path == plugin.target_dir / "sub/test.md"

    async def test_fetch_returns_ref_result(self, plugin: FileInputPlugin) -> None:
        model_file = plugin.model_dirs[0] / "test.md"
        model_file.write_text("""\
---
name: Test Document
description: A test
---

Template content here.
""")
        target_file = plugin.target_dir / "test.md"
        target_file.write_text("Compiled output")

        result = await plugin.fetch("test")

        assert result.name == "Test Document"
        assert result.description == "A test"
        assert result.content == "Compiled output"
        assert "Template content here." in result.template
        assert result.uri == "test"

    async def test_fetch_uses_uri_as_name_fallback(self, plugin: FileInputPlugin) -> None:
        model_file = plugin.model_dirs[0] / "my-doc.md"
        model_file.write_text("---\n---\nContent")
        target_file = plugin.target_dir / "my-doc.md"
        target_file.write_text("Output")

        result = await plugin.fetch("my-doc")
        assert result.name == "my-doc"

    async def test_fetch_not_found(self, plugin: FileInputPlugin) -> None:
        with pytest.raises(FileNotFoundError):
            await plugin.fetch("nonexistent")

    async def test_hash_returns_consistent_value(self, plugin: FileInputPlugin) -> None:
        model_file = plugin.model_dirs[0] / "test.md"
        model_file.write_text("content here")

        hash1 = await plugin.hash("test")
        hash2 = await plugin.hash("test")

        assert hash1 == hash2
        assert len(hash1) == 16

    async def test_hash_changes_with_content(self, plugin: FileInputPlugin) -> None:
        model_file = plugin.model_dirs[0] / "test.md"
        model_file.write_text("content A")
        hash1 = await plugin.hash("test")

        model_file.write_text("content B")
        hash2 = await plugin.hash("test")

        assert hash1 != hash2

    async def test_hash_not_found(self, plugin: FileInputPlugin) -> None:
        with pytest.raises(FileNotFoundError):
            await plugin.hash("nonexistent")

    def test_discover_documents_empty(self, plugin: FileInputPlugin) -> None:
        docs = plugin.discover_documents()
        assert docs == []

    def test_discover_documents_finds_files(self, plugin: FileInputPlugin) -> None:
        (plugin.model_dirs[0] / "a.md").write_text("a")
        (plugin.model_dirs[0] / "b.md").write_text("b")

        docs = plugin.discover_documents()
        uris = [uri for uri, _ in docs]

        assert set(uris) == {"a", "b"}

    def test_discover_documents_nested(self, plugin: FileInputPlugin) -> None:
        (plugin.model_dirs[0] / "root.md").write_text("r")
        nested = plugin.model_dirs[0] / "sub"
        nested.mkdir()
        (nested / "nested.md").write_text("n")

        docs = plugin.discover_documents()
        uris = [uri for uri, _ in docs]

        assert set(uris) == {"root", "sub/nested"}

    def test_discover_documents_sorted(self, plugin: FileInputPlugin) -> None:
        (plugin.model_dirs[0] / "z.md").write_text("z")
        (plugin.model_dirs[0] / "a.md").write_text("a")
        (plugin.model_dirs[0] / "m.md").write_text("m")

        docs = plugin.discover_documents()
        uris = [uri for uri, _ in docs]

        assert uris == ["a", "m", "z"]

    def test_parse_frontmatter_with_colin_config(self, plugin: FileInputPlugin) -> None:
        model_file = plugin.model_dirs[0] / "test.md"
        model_file.write_text("""\
---
colin:
  output: skill
  refresh: 1h
name: Test
---

Content here.
""")

        fm, content = plugin.parse_frontmatter(model_file)

        assert fm.colin.output == "skill"
        assert fm.colin.refresh == "1h"
        assert fm.metadata["name"] == "Test"
        assert "Content here." in content

    def test_parse_frontmatter_without_colin_config(self, plugin: FileInputPlugin) -> None:
        model_file = plugin.model_dirs[0] / "test.md"
        model_file.write_text("""\
---
name: Test
description: A test document
---

Content here.
""")

        fm, content = plugin.parse_frontmatter(model_file)

        assert fm.colin.output == "markdown"
        assert fm.metadata["name"] == "Test"
        assert fm.metadata["description"] == "A test document"

    def test_parse_frontmatter_empty(self, plugin: FileInputPlugin) -> None:
        model_file = plugin.model_dirs[0] / "test.md"
        model_file.write_text("No frontmatter here.")

        fm, content = plugin.parse_frontmatter(model_file)

        assert fm.colin.output == "markdown"
        assert fm.metadata == {}
        assert "No frontmatter here." in content

    def test_discover_excludes_target_directory(self, plugin: FileInputPlugin) -> None:
        # Create model file
        (plugin.model_dirs[0] / "model.md").write_text("model")

        # Create file in target directory (should be excluded)
        plugin.target_dir.mkdir(exist_ok=True)
        (plugin.target_dir / "target.md").write_text("target")

        docs = plugin.discover_documents()
        uris = [uri for uri, _ in docs]

        assert "model" in uris
        assert "target" not in uris

    def test_discover_excludes_nested_projects(self, plugin: FileInputPlugin) -> None:
        # Create model file in root
        (plugin.model_dirs[0] / "root.md").write_text("root")

        # Create nested project with its own colin.toml
        nested = plugin.model_dirs[0] / "nested_project"
        nested.mkdir()
        (nested / "colin.toml").write_text("[project]\nname = 'nested'")
        (nested / "nested.md").write_text("nested")

        docs = plugin.discover_documents()
        uris = [uri for uri, _ in docs]

        assert "root" in uris
        assert "nested_project/nested" not in uris
