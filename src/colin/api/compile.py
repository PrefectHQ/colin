"""Compilation API functions."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from colin.api.manifest import load_manifest, save_manifest
from colin.api.project import (
    create_project,
    find_project_file,
    load_project,
)
from colin.compiler import CompileEngine
from colin.llm.stub import StubLLMProvider
from colin.models import CompiledDocument, Manifest
from colin.plugins.inputs.file import FileInputPlugin
from colin.settings import settings

if TYPE_CHECKING:
    from colin.llm.base import LLMProvider


class CompileResult:
    """Result from a compilation operation."""

    def __init__(
        self,
        compiled: list[CompiledDocument],
        manifest: Manifest,
        project_name: str | None,
    ) -> None:
        """Initialize compile result.

        Args:
            compiled: List of compiled documents.
            manifest: Updated manifest.
            project_name: Name of the project.
        """
        self.compiled = compiled
        self.manifest = manifest
        self.project_name = project_name

    @property
    def total_llm_calls(self) -> int:
        """Total number of LLM calls across all documents."""
        return sum(len(doc.llm_calls) for doc in self.compiled)

    @property
    def total_cost(self) -> float:
        """Total cost in USD across all documents."""
        return sum(doc.total_cost_usd for doc in self.compiled)


async def compile_project(
    project_dir: Path,
    *,
    target_dir: Path | None = None,
    force: bool = False,
    llm_provider: LLMProvider | None = None,
    init_if_missing: bool = False,
    dry_run: bool = False,
) -> CompileResult | list[tuple[str, Path]]:
    """Compile all documents in a project.

    Args:
        project_dir: Project directory (should contain colin.toml or models/).
        target_dir: Override target directory (default: from colin.toml or ./target/).
        force: Force recompile all documents.
        llm_provider: LLM provider to use (default: StubLLMProvider).
        init_if_missing: Create colin.toml if it doesn't exist.
        dry_run: If True, return list of (uri, path) tuples instead of compiling.

    Returns:
        CompileResult with compiled documents and manifest, or list of (uri, path) if dry_run.

    Raises:
        FileNotFoundError: If project directory doesn't exist.
        ValueError: If no models found and init_if_missing is False.
    """
    project_dir = project_dir.resolve()

    # Find or create project file
    project_file = find_project_file(project_dir)

    if project_file:
        config = load_project(project_file)
        project_name = config.name
        model_dir = (project_file.parent / config.model_path).resolve()
        target_dir = target_dir or (project_file.parent / config.target_path).resolve()
    else:
        project_name = None
        model_dir = (project_dir / "models").resolve()

        if not model_dir.exists():
            if not init_if_missing:
                raise ValueError(
                    f"Models directory not found: {model_dir}. "
                    "Use init_if_missing=True to create a project."
                )
            # Will create project below

        model_files = list(model_dir.rglob("*.md")) if model_dir.exists() else []
        if not model_files:
            if not init_if_missing:
                raise ValueError(
                    f"No .md files found in: {model_dir}. "
                    "Use init_if_missing=True to create a project."
                )

        if init_if_missing:
            project_file = create_project(project_dir, name=project_dir.name)
            project_name = project_dir.name
            config = load_project(project_file)
            target_dir = target_dir or (project_dir / config.target_path).resolve()
        else:
            raise ValueError(
                f"No colin.toml found in {project_dir}. "
                "Use init_if_missing=True to create one."
            )

    # Set up input plugin
    compiled_dir = target_dir / "compiled"
    input_plugin = FileInputPlugin(model_dirs=[model_dir], target_dir=compiled_dir)

    # Handle dry run
    if dry_run:
        documents = input_plugin.discover_documents()
        return documents

    # Use provided LLM provider or default
    if llm_provider is None:
        llm_provider = StubLLMProvider()

    # Load or create manifest
    manifest_path = target_dir / settings.manifest_file
    manifest = Manifest() if force else load_manifest(manifest_path)

    # Create and run compiler
    engine = CompileEngine(
        manifest=manifest,
        input_plugin=input_plugin,
        llm_provider=llm_provider,
    )

    compiled = await engine.compile_all()

    # Save manifest
    target_dir.mkdir(parents=True, exist_ok=True)
    save_manifest(manifest, manifest_path)

    return CompileResult(
        compiled=compiled,
        manifest=manifest,
        project_name=project_name,
    )

