"""Tests for ref() validation - schemaless refs must be project-local."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from colin.compiler import CompileContext
from colin.compiler.context import _has_scheme
from colin.exceptions import RefNotFoundError
from colin.models import Manifest
from colin.plugins.inputs.file import ProjectInput

if TYPE_CHECKING:
    pass


class TestHasScheme:
    """Tests for the _has_scheme helper function."""

    def test_schemaless_uri(self) -> None:
        assert _has_scheme("reports/summary") is False

    def test_schemaless_simple(self) -> None:
        assert _has_scheme("greeting") is False

    def test_file_scheme(self) -> None:
        assert _has_scheme("file://path/to/file") is True

    def test_github_scheme(self) -> None:
        assert _has_scheme("github://org/repo/file.md") is True

    def test_mcp_scheme(self) -> None:
        assert _has_scheme("mcp://linear/issue/ABC-123") is True

    def test_https_scheme(self) -> None:
        assert _has_scheme("https://example.com/data") is True

    def test_colon_without_slashes(self) -> None:
        # A colon alone doesn't make a scheme
        assert _has_scheme("path:with:colons") is False


class TestSchemalessRefValidation:
    """Tests for schemaless ref validation at compile time."""

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
        input_plugin = ProjectInput(
            model_dirs=[source_dir],
            target_dir=output_dir,
        )

        context = CompileContext(
            manifest=manifest,
            document_uri="test-doc",
            default_model="test-model",
            input_plugin=input_plugin,
        )
        return context, source_dir, output_dir

    async def test_schemaless_ref_to_valid_file_passes_validation(
        self, project_setup: tuple[CompileContext, Path, Path]
    ) -> None:
        """Schemaless refs to existing project files should pass validation."""
        context, source_dir, output_dir = project_setup

        # Create a valid model file
        (source_dir / "greeting.md").write_text("---\nname: Greeting\n---\nHello!")
        (output_dir / "greeting.md").write_text("Hello!")

        # Should not raise - file exists in project
        result = await context.ref("greeting")
        assert result.content == "Hello!"

    async def test_schemaless_ref_to_nonexistent_file_raises(
        self, project_setup: tuple[CompileContext, Path, Path]
    ) -> None:
        """Schemaless refs to nonexistent files should raise RefNotFoundError."""
        context, source_dir, output_dir = project_setup

        # No files created - ref should fail validation
        with pytest.raises(RefNotFoundError) as exc_info:
            await context.ref("nonexistent")

        assert "nonexistent" in str(exc_info.value)
        assert "not found in project" in str(exc_info.value)

    async def test_schemaless_ref_to_nested_valid_file(
        self, project_setup: tuple[CompileContext, Path, Path]
    ) -> None:
        """Schemaless refs to nested paths should work if they exist."""
        context, source_dir, output_dir = project_setup

        # Create nested structure
        (source_dir / "reports").mkdir()
        (source_dir / "reports" / "quarterly.md").write_text("---\nname: Q\n---\nReport")
        (output_dir / "reports").mkdir()
        (output_dir / "reports" / "quarterly.md").write_text("Report")

        result = await context.ref("reports/quarterly")
        assert result.content == "Report"

    async def test_schemaless_ref_to_nested_nonexistent_raises(
        self, project_setup: tuple[CompileContext, Path, Path]
    ) -> None:
        """Schemaless refs to nonexistent nested paths should raise."""
        context, source_dir, output_dir = project_setup

        with pytest.raises(RefNotFoundError) as exc_info:
            await context.ref("reports/missing")

        assert "reports/missing" in str(exc_info.value)

    async def test_schemaless_ref_dependency_not_recorded_on_failure(
        self, project_setup: tuple[CompileContext, Path, Path]
    ) -> None:
        """Failed validation should not record the ref as a dependency."""
        context, source_dir, output_dir = project_setup

        with pytest.raises(RefNotFoundError):
            await context.ref("nonexistent")

        # Dependency should NOT be recorded since validation failed
        assert "nonexistent" not in context.refs_evaluated


class TestPathTraversalPrevention:
    """Tests that path traversal attempts are caught."""

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
        input_plugin = ProjectInput(
            model_dirs=[source_dir],
            target_dir=output_dir,
        )

        context = CompileContext(
            manifest=manifest,
            document_uri="test-doc",
            default_model="test-model",
            input_plugin=input_plugin,
        )
        return context, source_dir, output_dir

    async def test_path_traversal_outside_project_raises(
        self, project_setup: tuple[CompileContext, Path, Path]
    ) -> None:
        """Schemaless refs with ../ that escape project should fail."""
        context, source_dir, output_dir = project_setup

        # Attempt to reference file outside project via path traversal
        with pytest.raises(RefNotFoundError) as exc_info:
            await context.ref("../secret")

        assert "../secret" in str(exc_info.value)
        assert "not found in project" in str(exc_info.value)

    async def test_deep_path_traversal_raises(
        self, project_setup: tuple[CompileContext, Path, Path]
    ) -> None:
        """Deep path traversal attempts should fail."""
        context, source_dir, output_dir = project_setup

        with pytest.raises(RefNotFoundError):
            await context.ref("../../../../../../etc/passwd")
