"""Tests for --ephemeral mode."""

from __future__ import annotations

from pathlib import Path

from colin.api.compile import compile_project


class TestEphemeralMode:
    """Tests for ephemeral compilation mode."""

    async def test_ephemeral_does_not_write_manifest(self, tmp_path: Path) -> None:
        """Ephemeral mode should not write manifest to disk."""
        # Set up directories
        source_dir = tmp_path / "models"
        source_dir.mkdir()
        build_dir = tmp_path / ".colin"
        build_dir.mkdir()
        compiled_dir = build_dir / "compiled"
        compiled_dir.mkdir()

        # Create a simple model
        (source_dir / "test.md").write_text("Hello world")

        # Create colin.toml
        (tmp_path / "colin.toml").write_text("""
[project]
name = "test"
model-path = "models"
output-path = "output"
""")

        manifest_path = build_dir / "manifest.json"

        # Compile in ephemeral mode
        await compile_project(tmp_path, ephemeral=True)

        # Manifest should not exist
        assert not manifest_path.exists(), "Manifest should not be written in ephemeral mode"

    async def test_ephemeral_does_not_write_compiled_artifacts(self, tmp_path: Path) -> None:
        """Ephemeral mode should not write to .colin/compiled/."""
        # Set up directories
        source_dir = tmp_path / "models"
        source_dir.mkdir()
        build_dir = tmp_path / ".colin"
        build_dir.mkdir()
        compiled_dir = build_dir / "compiled"
        compiled_dir.mkdir()

        # Create a simple model
        (source_dir / "test.md").write_text("Hello world")

        # Create colin.toml
        (tmp_path / "colin.toml").write_text("""
[project]
name = "test"
model-path = "models"
output-path = "output"
""")

        # Compile in ephemeral mode
        await compile_project(tmp_path, ephemeral=True)

        # .colin/compiled/ should be empty (no artifacts written)
        compiled_files = list(compiled_dir.rglob("*"))
        assert len(compiled_files) == 0, "No artifacts should be written in ephemeral mode"

    async def test_ephemeral_still_writes_output(self, tmp_path: Path) -> None:
        """Ephemeral mode should still write to output/ directory."""
        # Set up directories - no .colin/ needed
        source_dir = tmp_path / "models"
        source_dir.mkdir()
        output_dir = tmp_path / "output"

        # Create a simple model
        (source_dir / "test.md").write_text("Hello world")

        # Create colin.toml
        (tmp_path / "colin.toml").write_text("""
[project]
name = "test"
model-path = "models"
output-path = "output"
""")

        # Compile in ephemeral mode
        await compile_project(tmp_path, ephemeral=True)

        # Output should exist
        assert output_dir.exists(), "Output directory should be created in ephemeral mode"
        assert (output_dir / "test.md").exists(), "Output file should be written"
        assert (output_dir / "test.md").read_text() == "Hello world"

    async def test_ephemeral_refs_work_in_memory(self, tmp_path: Path) -> None:
        """Refs should work in ephemeral mode using in-memory compiled outputs."""
        # Set up directories - no .colin/ needed
        source_dir = tmp_path / "models"
        source_dir.mkdir()
        output_dir = tmp_path / "output"

        # Create models with ref
        (source_dir / "base.md").write_text("Base content")
        (source_dir / "consumer.md").write_text("Consumed: {{ ref('base.md').content }}")

        # Create colin.toml
        (tmp_path / "colin.toml").write_text("""
[project]
name = "test"
model-path = "models"
output-path = "output"
""")

        # Compile in ephemeral mode
        await compile_project(tmp_path, ephemeral=True)

        # Ref should have resolved correctly
        assert (output_dir / "consumer.md").exists()
        content = (output_dir / "consumer.md").read_text()
        assert "Consumed: Base content" in content

    async def test_ephemeral_can_read_existing_cache(self, tmp_path: Path) -> None:
        """Ephemeral mode should be able to read from existing cache."""
        # Set up directories
        source_dir = tmp_path / "models"
        source_dir.mkdir()
        build_dir = tmp_path / ".colin"
        build_dir.mkdir()
        compiled_dir = build_dir / "compiled"
        compiled_dir.mkdir()

        # Create a simple model
        (source_dir / "test.md").write_text("Original content")

        # Create colin.toml
        (tmp_path / "colin.toml").write_text("""
[project]
name = "test"
model-path = "models"
output-path = "output"
""")

        # First, compile normally to populate cache
        await compile_project(tmp_path, ephemeral=False)

        # Verify manifest was written
        manifest_path = build_dir / "manifest.json"
        assert manifest_path.exists()
        manifest_mtime = manifest_path.stat().st_mtime

        # Verify compiled artifact exists
        assert (compiled_dir / "test.md").exists()

        # Now compile in ephemeral mode
        await compile_project(tmp_path, ephemeral=True)

        # Manifest should not have been modified
        assert manifest_path.stat().st_mtime == manifest_mtime

    async def test_no_cache_ephemeral_full_isolation(self, tmp_path: Path) -> None:
        """--no-cache --ephemeral should provide full isolation."""
        # Set up directories
        source_dir = tmp_path / "models"
        source_dir.mkdir()
        build_dir = tmp_path / ".colin"
        build_dir.mkdir()
        compiled_dir = build_dir / "compiled"
        compiled_dir.mkdir()
        output_dir = tmp_path / "output"

        # Create a simple model
        (source_dir / "test.md").write_text("Hello world")

        # Create colin.toml
        (tmp_path / "colin.toml").write_text("""
[project]
name = "test"
model-path = "models"
output-path = "output"
""")

        # Compile with both flags
        await compile_project(tmp_path, force=True, ephemeral=True)

        # No manifest
        assert not (build_dir / "manifest.json").exists()

        # No compiled artifacts
        assert len(list(compiled_dir.rglob("*"))) == 0

        # Output still written
        assert (output_dir / "test.md").exists()

    async def test_ephemeral_does_not_create_colin_directory(self, tmp_path: Path) -> None:
        """Ephemeral mode should not create .colin/ directory if it doesn't exist."""
        # Set up directories - notably, NO .colin/ directory
        source_dir = tmp_path / "models"
        source_dir.mkdir()
        build_dir = tmp_path / ".colin"
        output_dir = tmp_path / "output"

        # Create a simple model
        (source_dir / "test.md").write_text("Hello world")

        # Create colin.toml
        (tmp_path / "colin.toml").write_text("""
[project]
name = "test"
model-path = "models"
output-path = "output"
""")

        # Verify .colin doesn't exist
        assert not build_dir.exists()

        # Compile in ephemeral mode
        await compile_project(tmp_path, ephemeral=True)

        # .colin should NOT have been created
        assert not build_dir.exists(), ".colin/ should not be created in ephemeral mode"

        # Output should still exist
        assert output_dir.exists()
        assert (output_dir / "test.md").exists()

    async def test_ephemeral_private_files_not_published(self, tmp_path: Path) -> None:
        """Private files (underscore-prefixed) should not be published in ephemeral mode."""
        # Set up directories - no .colin/ needed
        source_dir = tmp_path / "models"
        source_dir.mkdir()
        output_dir = tmp_path / "output"

        # Create public and private models
        (source_dir / "public.md").write_text("Public content")
        (source_dir / "_private.md").write_text("Private content")

        # Create colin.toml
        (tmp_path / "colin.toml").write_text("""
[project]
name = "test"
model-path = "models"
output-path = "output"
""")

        # Compile in ephemeral mode
        await compile_project(tmp_path, ephemeral=True)

        # Public file should be in output
        assert (output_dir / "public.md").exists()
        assert (output_dir / "public.md").read_text() == "Public content"

        # Private file should NOT be in output
        assert not (output_dir / "_private.md").exists()

    async def test_ephemeral_publishes_fresh_content_over_stale_cache(self, tmp_path: Path) -> None:
        """Ephemeral mode should publish freshly compiled content, not stale cache."""
        # Set up directories
        source_dir = tmp_path / "models"
        source_dir.mkdir()
        output_dir = tmp_path / "output"

        # Create initial model
        (source_dir / "test.md").write_text("Original content")

        # Create colin.toml
        (tmp_path / "colin.toml").write_text("""
[project]
name = "test"
model-path = "models"
output-path = "output"
""")

        # First, compile normally to populate cache
        await compile_project(tmp_path, ephemeral=False)
        assert (output_dir / "test.md").read_text() == "Original content"

        # Now edit the source file
        (source_dir / "test.md").write_text("Updated content")

        # Compile in ephemeral mode - should publish fresh content, not stale cache
        await compile_project(tmp_path, ephemeral=True)

        # Output should have the NEW content, not the stale cached version
        assert (output_dir / "test.md").read_text() == "Updated content"
