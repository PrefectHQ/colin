"""Compilation API functions."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from colin.api.project import find_project_file, load_project
from colin.compiler import CompileEngine
from colin.compiler.state import CompilationState
from colin.exceptions import ProjectNotInitializedError
from colin.models import CompiledDocument, Manifest
from colin.providers.storage.file import FileStorage
from colin.settings import settings


def _save_manifest(manifest_path: Path, manifest: Manifest) -> None:
    """Save manifest to disk."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest.compiled_at = datetime.now(timezone.utc)
    content = manifest.model_dump_json(indent=2)
    manifest_path.write_text(content, encoding="utf-8")


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
    state: CompilationState | None = None,
) -> CompileResult | list[tuple[str, Path]]:
    """Compile all documents in a project.

    Args:
        project_dir: Project directory (must contain colin.toml).
        target_dir: Override target directory (default: from colin.toml).
        force: Force recompile all documents.
        default_model: Override default LLM model.
        dry_run: If True, return list of (uri, path) tuples instead of compiling.
        state: Optional compilation state for progress tracking.

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

    # Override target_dir if provided (need to update config paths)
    if target_dir is not None:
        target_dir = target_dir.resolve()
        # Update config paths that depend on target_dir
        from colin.api.project import ProjectConfig

        config = ProjectConfig(
            name=config.name,
            project_root=config.project_root,
            model_path=config.model_path,
            target_path=target_dir,
            manifest_path=target_dir / settings.manifest_file,
            default_llm_model=config.default_llm_model,
            mcp=config.mcp,
            project_storage=config.project_storage,
            artifacts_storage=config.artifacts_storage,
            providers=config.providers,
        )

    # Compiled outputs go in target/compiled
    compiled_dir = config.target_path / "compiled"

    # Handle dry run - discover models directly
    if dry_run:
        uris: list[tuple[str, Path]] = []
        if config.model_path.exists():
            for path in config.model_path.rglob("*.md"):
                relative = path.relative_to(config.model_path)
                uri = f"project://{relative}"
                uris.append((uri, compiled_dir / str(relative)))
        return sorted(uris, key=lambda x: x[0])

    # Resolve model: param > project config > settings
    effective_model = default_model or config.default_llm_model or settings.default_llm_model

    # Create artifact storage (FileStorage with base at compiled_dir)
    artifact_storage = FileStorage(base_path=compiled_dir)

    # Create and run compiler (engine loads manifest from config)
    engine = CompileEngine(
        config=config,
        artifact_storage=artifact_storage,
        default_model=effective_model,
        state=state,
        force=force,
    )

    compiled = await engine.compile_all()

    # Save manifest
    _save_manifest(config.manifest_path, engine.manifest)

    return CompileResult(
        compiled=compiled,
        manifest=engine.manifest,
        project_name=config.name,
    )
