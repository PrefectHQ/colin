"""Project management API functions."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import tomli
import tomli_w
from pydantic import BaseModel

from colin.api.manifest import load_manifest
from colin.settings import settings

PROJECT_FILE = "colin.toml"

DEFAULT_CONFIG = """\
# Colin project configuration
# https://github.com/jlowin/colin

[project]
name = "{name}"

# model-path = "models"
# target-path = "target"
"""


class ProjectConfig(BaseModel):
    """Colin project configuration."""

    name: str = "colin-project"
    model_path: str = "models"
    target_path: str = "target"


def find_project_file(start: Path | None = None) -> Path | None:
    """Find colin.toml by walking up from start directory.

    Args:
        start: Directory to start searching from (default: cwd).

    Returns:
        Path to colin.toml if found, None otherwise.
    """
    current = (start or Path.cwd()).resolve()

    while current != current.parent:
        project_file = current / PROJECT_FILE
        if project_file.exists():
            return project_file
        current = current.parent

    return None


def load_project(path: Path) -> ProjectConfig:
    """Load project configuration from colin.toml.

    Args:
        path: Path to colin.toml file.

    Returns:
        ProjectConfig with settings.
    """
    with open(path, "rb") as f:
        data = tomli.load(f)

    project = data.get("project", {})

    return ProjectConfig(
        name=project.get("name", "colin-project"),
        model_path=project.get("model-path", "models"),
        target_path=project.get("target-path", "target"),
    )


def create_project(directory: Path, name: str | None = None) -> Path:
    """Create a new colin.toml project file.

    Args:
        directory: Directory to create project in.
        name: Project name (default: directory name).

    Returns:
        Path to created colin.toml.
    """
    project_file = directory / PROJECT_FILE
    project_name = name or directory.name

    content = DEFAULT_CONFIG.format(name=project_name)
    project_file.write_text(content)

    return project_file


def init_project(
    directory: Path,
    name: str | None = None,
    model_path: str = "models",
    target_path: str = "target",
) -> tuple[Path, Path]:
    """Initialize a new Colin project with colin.toml and models directory.

    Args:
        directory: Directory to create project in.
        name: Project name (default: directory name).
        model_path: Path to models directory (default: "models").
        target_path: Path to target directory (default: "target").

    Returns:
        Tuple of (colin.toml path, models directory path).

    Raises:
        FileExistsError: If colin.toml already exists.
    """
    project_file = directory / PROJECT_FILE

    if project_file.exists():
        raise FileExistsError(f"Project already exists: {project_file}")

    # Create colin.toml with full config
    project_name = name or directory.name
    config = ProjectConfig(
        name=project_name,
        model_path=model_path,
        target_path=target_path,
    )
    save_project(project_file, config)

    # Create models directory
    model_dir = directory / model_path
    model_dir.mkdir(parents=True, exist_ok=True)

    return project_file, model_dir


def save_project(path: Path, config: ProjectConfig) -> None:
    """Save project configuration to colin.toml.

    Args:
        path: Path to colin.toml file.
        config: Configuration to save.
    """
    data: dict[str, Any] = {
        "project": {
            "name": config.name,
            "model-path": config.model_path,
            "target-path": config.target_path,
        },
    }
    with open(path, "wb") as f:
        tomli_w.dump(data, f)


def get_project_status(project_dir: Path) -> dict:
    """Get status information for a project.

    Args:
        project_dir: Project directory.

    Returns:
        Dictionary with status information:
        - project_name: Name of the project
        - target_dir: Target directory path
        - manifest_exists: Whether manifest.json exists
        - document_count: Number of documents in manifest
        - total_llm_calls: Total LLM calls across all documents
        - total_cost: Total cost in USD
        - compiled_at: Last compilation timestamp
    """
    project_file = find_project_file(project_dir.resolve())

    if project_file:
        config = load_project(project_file)
        project_name = config.name
        target_dir = project_file.parent / config.target_path
    else:
        project_dir = project_dir.resolve()
        project_name = project_dir.name
        target_dir = project_dir / "target"

    manifest_path = target_dir / settings.manifest_file
    manifest = load_manifest(manifest_path)

    total_llm_calls = sum(len(doc.llm_calls) for doc in manifest.documents.values())
    total_cost = sum(doc.total_cost_usd for doc in manifest.documents.values())

    return {
        "project_name": project_name,
        "target_dir": target_dir,
        "manifest_exists": manifest_path.exists(),
        "document_count": len(manifest.documents),
        "total_llm_calls": total_llm_calls,
        "total_cost": total_cost,
        "compiled_at": manifest.compiled_at,
        "documents": {
            uri: {
                "llm_calls": len(meta.llm_calls),
                "cost": meta.total_cost_usd,
            }
            for uri, meta in manifest.documents.items()
        },
    }


def clean_project(project_dir: Path) -> list[Path]:
    """Remove target directory and all compiled outputs.

    Args:
        project_dir: Project directory.

    Returns:
        List of paths that were removed.
    """
    project_file = find_project_file(project_dir.resolve())

    if project_file:
        config = load_project(project_file)
        target_dir = project_file.parent / config.target_path
    else:
        target_dir = project_dir.resolve() / "target"

    if not target_dir.exists():
        return []

    # Collect files before removal
    removed_files = [path for path in target_dir.rglob("*") if path.is_file()]

    # Remove directory
    shutil.rmtree(target_dir)

    return removed_files
