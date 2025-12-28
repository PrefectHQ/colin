"""Compilation API functions."""

from __future__ import annotations

from pathlib import Path

from colin.api.manifest import load_manifest, save_manifest
from colin.api.project import find_project_file, load_project
from colin.compiler import CompileEngine
from colin.exceptions import ProjectNotInitializedError
from colin.models import CompiledDocument, Manifest
from colin.plugins.inputs.file import FileInputPlugin
from colin.settings import settings


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
    default_model: str | None = None,
    dry_run: bool = False,
) -> CompileResult | list[tuple[str, Path]]:
    """Compile all documents in a project.

    Args:
        project_dir: Project directory (must contain colin.toml).
        target_dir: Override target directory (default: from colin.toml).
        force: Force recompile all documents.
        default_model: Override default LLM model.
        dry_run: If True, return list of (uri, path) tuples instead of compiling.

    Returns:
        CompileResult with compiled documents and manifest, or list of (uri, path) if dry_run.

    Raises:
        ProjectNotInitializedError: If no colin.toml found.
    """
    project_dir = project_dir.resolve()

    # Find project file - required
    project_file = find_project_file(project_dir)

    if not project_file:
        raise ProjectNotInitializedError(f"No colin.toml found in {project_dir}")

    config = load_project(project_file)
    project_name = config.name
    model_dir = (project_file.parent / config.model_path).resolve()
    target_dir = target_dir or (project_file.parent / config.target_path).resolve()

    # Set up input plugin
    compiled_dir = target_dir / "compiled"
    input_plugin = FileInputPlugin(model_dirs=[model_dir], target_dir=compiled_dir)

    # Handle dry run
    if dry_run:
        documents = input_plugin.discover_documents()
        return documents

    # Resolve model: param > project config > settings
    effective_model = default_model or config.default_llm_model or settings.default_llm_model

    # Load or create manifest
    manifest_path = target_dir / settings.manifest_file
    manifest = Manifest() if force else load_manifest(manifest_path)

    # Create and run compiler
    engine = CompileEngine(
        manifest=manifest,
        input_plugin=input_plugin,
        default_model=effective_model,
        mcp_config=config.mcp,
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
