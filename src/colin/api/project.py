"""Project management API functions."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Literal

import tomli
import tomli_w
from pydantic import BaseModel, Field, model_validator

from colin.api.manifest import load_manifest
from colin.settings import settings

logger = logging.getLogger(__name__)

VarType = Literal["string", "bool", "int", "float", "date", "timestamp"]

PROJECT_FILE = "colin.toml"

DEFAULT_CONFIG = """\
# Colin project configuration
# https://github.com/prefecthq/colin

[project]
name = "{name}"

# model-path = "models"
# output-path = "output"
"""


class StorageConfig(BaseModel):
    """Configuration for project or artifacts storage."""

    provider: str = "file"
    config: dict[str, Any] = Field(default_factory=dict)


class VarConfig(BaseModel):
    """Configuration for a project variable.

    Variables can be defined in colin.toml and accessed in templates via `vars.*`.
    Resolution logic lives in VariableProvider.
    """

    type: VarType = "string"
    """Type of the variable (string, bool, int, float, date, timestamp)."""

    default: str | bool | int | float | None = None
    """Default value."""

    optional: bool = False
    """If True and no default, the variable returns None instead of erroring."""


class ProviderInstanceConfig(BaseModel):
    """Configuration for a provider instance."""

    provider_type: str
    """Provider type name (e.g., 's3', 'mcp')."""

    name: str | None = None
    """Instance name from the 'name' field in colin.toml.

    Example:
        [[providers.s3]]
        name = "dev"

        [[providers.s3]]
        name = "prod"

    Creates two S3 provider instances with schemes 's3.dev' and 's3.prod'.
    """

    schemes: list[str] | None = None
    """Explicit list of URI schemes this instance handles. If not set, defaults
    to ['{provider_type}.{name}'] for named instances or ['{provider_type}'] for unnamed."""

    config: dict[str, Any] = Field(default_factory=dict)
    """Provider-specific configuration."""

    @model_validator(mode="after")
    def _validate_names(self) -> ProviderInstanceConfig:
        if self.name is not None and not str(self.name).strip():
            raise ValueError("Provider name cannot be empty")
        if self.schemes is not None:
            cleaned = []
            for scheme in self.schemes:
                if not str(scheme).strip():
                    raise ValueError("schemes cannot contain empty strings")
                cleaned.append(scheme.rstrip(":/"))
            self.schemes = cleaned
        return self

    def get_schemes(self) -> list[str]:
        """Get URI schemes this instance handles.

        If schemes is explicitly set, returns that list.
        Otherwise returns default based on provider_type and name.
        """
        if self.schemes is not None:
            return self.schemes
        if self.name:
            return [f"{self.provider_type}.{self.name}"]
        return [self.provider_type]

    @property
    def config_hash(self) -> str:
        """Hash of provider config for staleness tracking.

        Used to detect when provider configuration changes, which should
        invalidate cached documents that use this provider.
        """
        content = json.dumps(self.config, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]


class ProjectConfig(BaseModel):
    """Colin project configuration with resolved paths.

    All paths are absolute and resolved at load time.
    """

    name: str = "colin-project"
    project_root: Path
    """Absolute path to project directory (where colin.toml lives)."""
    model_path: Path
    """Absolute path to models directory."""
    output_path: Path
    """Absolute path to output directory (published outputs)."""
    manifest_path: Path
    """Absolute path to manifest file (.colin/manifest.json)."""

    # Provider configuration
    project_storage: StorageConfig = Field(default_factory=StorageConfig)
    artifacts_storage: StorageConfig | None = None
    providers: dict[str, ProviderInstanceConfig] = Field(default_factory=dict)

    # Project variables
    vars: dict[str, VarConfig] = Field(default_factory=dict)
    """Project variables accessible in templates via `vars.*`."""

    model_config = {"arbitrary_types_allowed": True}

    @property
    def build_path(self) -> Path:
        """Fixed location for build artifacts: .colin/"""
        return self.project_root / ".colin"


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


def _parse_providers(providers_data: dict[str, Any]) -> dict[str, ProviderInstanceConfig]:
    """Parse [[providers.*]] configuration into ProviderInstanceConfig instances.

    Each provider type uses array-of-table entries:
    - [[providers.s3]] name omitted → schemes ['s3']
    - [[providers.s3]] name = 'dev' → schemes ['s3.dev']
    - [[providers.s3]] schemes = ['s3', 's3.prod'] → explicit schemes

    Args:
        providers_data: Raw providers section from TOML.

    Returns:
        Dictionary mapping scheme to ProviderInstanceConfig.
        If multiple instances claim the same scheme, last one wins with a warning.
    """
    result: dict[str, ProviderInstanceConfig] = {}
    defaults_seen: set[str] = set()
    names_seen: dict[str, set[str]] = {}

    for provider_type, value in providers_data.items():
        if not isinstance(value, list):
            raise ValueError(
                f"[providers.{provider_type}] must use array-of-tables "
                f"([[providers.{provider_type}]])"
            )

        for entry in value:
            if not isinstance(entry, dict):
                raise ValueError(
                    f"Provider config for {provider_type} must be a table, got {type(entry)}"
                )

            name = entry.get("name")
            schemes = entry.get("schemes")

            if name is None:
                if provider_type in defaults_seen:
                    raise ValueError(
                        f"[providers.{provider_type}] only one default instance is allowed"
                    )
                defaults_seen.add(provider_type)
            else:
                seen = names_seen.setdefault(provider_type, set())
                if name in seen:
                    raise ValueError(f"[providers.{provider_type}] duplicate name '{name}'")
                seen.add(name)

            config = {key: val for key, val in entry.items() if key not in {"name", "schemes"}}

            instance = ProviderInstanceConfig(
                provider_type=provider_type,
                name=name,
                schemes=schemes,
                config=config,
            )

            # Register all schemes for this instance
            for scheme in instance.get_schemes():
                if scheme in result:
                    logger.warning(
                        "Scheme '%s' already registered, overwriting with providers.%s",
                        scheme,
                        provider_type,
                    )
                result[scheme] = instance

    return result


def _parse_vars(vars_data: dict[str, Any]) -> dict[str, VarConfig]:
    """Parse [vars] configuration into VarConfig instances.

    Supports two syntaxes:
    - Simple: `name = "value"` creates a string var with default
    - Typed: `[vars.name]` subsection with type, default, optional fields

    Args:
        vars_data: Raw vars section from TOML.

    Returns:
        Dictionary mapping variable name to VarConfig.

    Raises:
        ValueError: If two variable names collide case-insensitively.
    """
    result: dict[str, VarConfig] = {}
    seen_lower: dict[str, str] = {}  # lowercase -> original name

    for name, value in vars_data.items():
        # Check for case-insensitive collision
        lower_name = name.lower()
        if lower_name in seen_lower:
            raise ValueError(
                f"Variable names '{seen_lower[lower_name]}' and '{name}' collide (case-insensitive)"
            )
        seen_lower[lower_name] = name

        if isinstance(value, (str, bool, int, float)):
            # Simple syntax: infer type from value
            if isinstance(value, bool):
                var_type: VarType = "bool"
            elif isinstance(value, int):
                var_type = "int"
            elif isinstance(value, float):
                var_type = "float"
            else:
                var_type = "string"
            result[name] = VarConfig(type=var_type, default=value)
        elif isinstance(value, dict):
            # Typed syntax with subsection
            result[name] = VarConfig.model_validate(value)
        else:
            raise ValueError(
                f"Variable '{name}' must be a string, number, bool, or table, "
                f"got {type(value).__name__}"
            )

    return result


def load_project(path: Path) -> ProjectConfig:
    """Load project configuration from colin.toml.

    Args:
        path: Path to colin.toml file.

    Returns:
        ProjectConfig with resolved absolute paths.
    """
    with open(path, "rb") as f:
        data = tomli.load(f)

    if "mcp" in data:
        raise ValueError("MCP servers must be configured under [[providers.mcp]]")

    project = data.get("project", {})
    # Resolve paths relative to project root (or use absolute if specified)
    project_root = path.parent.resolve()
    model_path_rel = project.get("model-path", "models")
    output_path_rel = project.get("output-path", "output")
    manifest_path_rel = project.get("manifest-path")

    # Handle absolute paths
    if Path(model_path_rel).is_absolute():
        model_path = Path(model_path_rel).resolve()
    else:
        model_path = (project_root / model_path_rel).resolve()

    if Path(output_path_rel).is_absolute():
        output_path = Path(output_path_rel).resolve()
    else:
        output_path = (project_root / output_path_rel).resolve()

    # Manifest path: explicit config or default to .colin/manifest.json
    if manifest_path_rel:
        if Path(manifest_path_rel).is_absolute():
            manifest_path = Path(manifest_path_rel).resolve()
        else:
            manifest_path = (project_root / manifest_path_rel).resolve()
    else:
        manifest_path = project_root / ".colin" / settings.manifest_file

    # Parse project storage config
    project_storage_data = project.get("storage", {})
    project_storage = StorageConfig(
        provider=project_storage_data.get("provider", "file"),
        config={k: v for k, v in project_storage_data.items() if k != "provider"},
    )

    # Parse artifacts storage config (optional, defaults to project storage)
    artifacts_data = data.get("artifacts", {})
    artifacts_storage_data = artifacts_data.get("storage")
    artifacts_storage = None
    if artifacts_storage_data:
        artifacts_storage = StorageConfig(
            provider=artifacts_storage_data.get("provider", "file"),
            config={k: v for k, v in artifacts_storage_data.items() if k != "provider"},
        )

    # Parse provider instances
    providers_data = data.get("providers", {})
    providers = _parse_providers(providers_data)

    # Parse project variables
    vars_data = data.get("vars", {})
    vars_config = _parse_vars(vars_data)

    return ProjectConfig(
        name=project.get("name", "colin-project"),
        project_root=project_root,
        model_path=model_path,
        output_path=output_path,
        manifest_path=manifest_path,
        project_storage=project_storage,
        artifacts_storage=artifacts_storage,
        providers=providers,
        vars=vars_config,
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
    model_path_rel: str = "models",
    output_path_rel: str = "output",
) -> tuple[Path, Path]:
    """Initialize a new Colin project with colin.toml and models directory.

    Args:
        directory: Directory to create project in.
        name: Project name (default: directory name).
        model_path_rel: Relative path to models directory (default: "models").
        output_path_rel: Relative path to output directory (default: "output").

    Returns:
        Tuple of (colin.toml path, models directory path).

    Raises:
        FileExistsError: If colin.toml already exists.
    """
    project_file = directory / PROJECT_FILE

    if project_file.exists():
        raise FileExistsError(f"Project already exists: {project_file}")

    # Resolve paths
    project_root = directory.resolve()
    model_path = (project_root / model_path_rel).resolve()
    output_path = (project_root / output_path_rel).resolve()
    manifest_path = project_root / ".colin" / settings.manifest_file

    # Create colin.toml with full config
    project_name = name or directory.name
    config = ProjectConfig(
        name=project_name,
        project_root=project_root,
        model_path=model_path,
        output_path=output_path,
        manifest_path=manifest_path,
    )
    # Create project directory and models subdirectory
    model_path.mkdir(parents=True, exist_ok=True)

    save_project(project_file, config)

    return project_file, model_path


def save_project(path: Path, config: ProjectConfig) -> None:
    """Save project configuration to colin.toml.

    Converts absolute paths back to relative paths for serialization when possible.
    Preserves absolute paths if they're outside the project root.

    Args:
        path: Path to colin.toml file.
        config: Configuration to save.
    """
    # Convert absolute paths to relative for TOML (if possible)
    try:
        model_path_rel = config.model_path.relative_to(config.project_root)
    except ValueError:
        # Absolute path outside project root - keep as absolute
        model_path_rel = str(config.model_path)

    try:
        output_path_rel = config.output_path.relative_to(config.project_root)
    except ValueError:
        # Absolute path outside project root - keep as absolute
        output_path_rel = str(config.output_path)

    project_data: dict[str, Any] = {
        "name": config.name,
        "model-path": str(model_path_rel),
        "output-path": str(output_path_rel),
    }

    data: dict[str, Any] = {"project": project_data}

    providers_data: dict[str, list[dict[str, Any]]] = {}
    for instance in config.providers.values():
        entry = dict(instance.config)
        if instance.name is not None:
            entry["name"] = instance.name
        if instance.schemes is not None:
            entry["schemes"] = instance.schemes
        providers_data.setdefault(instance.provider_type, []).append(entry)

    if providers_data:
        data["providers"] = providers_data

    # Serialize vars
    if config.vars:
        vars_data: dict[str, Any] = {}
        for var_name, var_config in config.vars.items():
            # Use simple syntax if only default is set (no special type, not optional)
            if (
                var_config.type == "string"
                and not var_config.optional
                and var_config.default is not None
            ):
                vars_data[var_name] = var_config.default
            elif (
                var_config.type in ("bool", "int", "float")
                and not var_config.optional
                and var_config.default is not None
            ):
                vars_data[var_name] = var_config.default
            else:
                # Use typed subsection syntax
                var_entry: dict[str, Any] = {}
                if var_config.type != "string":
                    var_entry["type"] = var_config.type
                if var_config.default is not None:
                    var_entry["default"] = var_config.default
                if var_config.optional:
                    var_entry["optional"] = True
                vars_data[var_name] = var_entry
        data["vars"] = vars_data

    with open(path, "wb") as f:
        tomli_w.dump(data, f)


def get_project_status(project_dir: Path) -> dict:
    """Get status information for a project.

    Args:
        project_dir: Project directory.

    Returns:
        Dictionary with status information:
        - project_file: Path to colin.toml (or None if not found)
        - config: ProjectConfig (or None if not found)
        - project_name: Name of the project
        - output_dir: Output directory path
        - manifest_exists: Whether manifest.json exists
        - document_count: Number of documents in manifest
        - total_llm_calls: Total LLM calls across all documents
        - total_cost: Total cost in USD
        - compiled_at: Last compilation timestamp
        - stale_files: List of stale file paths
    """
    project_file = find_project_file(project_dir.resolve())

    if not project_file:
        return {
            "project_file": None,
            "config": None,
            "project_name": project_dir.name,
            "output_dir": project_dir / "output",
            "manifest_exists": False,
            "document_count": 0,
            "total_llm_calls": 0,
            "total_cost": 0.0,
            "compiled_at": None,
            "stale_files": [],
            "documents": {},
        }

    config = load_project(project_file)
    manifest = load_manifest(config.manifest_path)

    total_llm_calls = sum(len(doc.llm_calls) for doc in manifest.documents.values())
    total_cost = sum(doc.total_cost_usd for doc in manifest.documents.values())

    return {
        "project_file": project_file,
        "config": config,
        "project_name": config.name,
        "output_dir": config.output_path,
        "manifest_exists": config.manifest_path.exists(),
        "document_count": len(manifest.documents),
        "total_llm_calls": total_llm_calls,
        "total_cost": total_cost,
        "compiled_at": manifest.compiled_at,
        "stale_files": get_stale_files(config),
        "documents": {
            uri: {
                "llm_calls": len(meta.llm_calls),
                "cost": meta.total_cost_usd,
            }
            for uri, meta in manifest.documents.items()
        },
    }


def get_stale_files(
    config: ProjectConfig,
    include_compiled: bool = False,
) -> list[Path]:
    """Find stale files in output/ (and optionally .colin/compiled/).

    A "stale file" is any file that isn't tracked by the manifest.
    In output/, this means files not published by any document.
    In .colin/compiled/, this means files not matching any document's output path.

    Args:
        config: Project configuration.
        include_compiled: If True, also check .colin/compiled/ for stale files.

    Returns:
        List of absolute paths to stale files, sorted alphabetically.
    """
    output_dir = config.output_path
    compiled_dir = config.build_path / "compiled"
    manifest = load_manifest(config.manifest_path)

    # Get published output paths from manifest
    published_paths: set[str] = set()
    for doc in manifest.documents.values():
        if doc.output_path and doc.is_published:
            published_paths.add(doc.output_path)

    # Get all output paths (published or not) for compiled dir check
    all_output_paths: set[str] = set()
    for doc in manifest.documents.values():
        if doc.output_path:
            all_output_paths.add(doc.output_path)

    stale: list[Path] = []

    # Check output/ for stale files (only published paths matter)
    if output_dir.exists():
        for path in output_dir.rglob("*"):
            if path.is_file():
                try:
                    rel_path = str(path.relative_to(output_dir))
                    if rel_path not in published_paths:
                        stale.append(path)
                except ValueError:
                    stale.append(path)

    # Optionally check .colin/compiled/ for stale files
    if include_compiled and compiled_dir.exists():
        for path in compiled_dir.rglob("*"):
            if path.is_file():
                try:
                    rel_path = str(path.relative_to(compiled_dir))
                    if rel_path not in all_output_paths:
                        stale.append(path)
                except ValueError:
                    stale.append(path)

    return sorted(stale)


def clean_project(config: ProjectConfig, all: bool = False) -> list[Path]:
    """Remove stale files from the project.

    Args:
        config: Project configuration.
        all: If True, remove stale files from both output/ and .colin/compiled/.
             If False (default), only remove stale files from output/.

    Returns:
        List of paths that were removed.
    """
    removed: list[Path] = []

    # Get stale files from output/ (and optionally .colin/compiled/)
    stale_files = get_stale_files(config, include_compiled=all)
    for path in stale_files:
        path.unlink()
        removed.append(path)

    # Clean up empty directories
    if config.output_path.exists():
        _remove_empty_dirs(config.output_path)
    if all:
        compiled_dir = config.build_path / "compiled"
        if compiled_dir.exists():
            _remove_empty_dirs(compiled_dir)

    return sorted(removed)


def _remove_empty_dirs(directory: Path) -> None:
    """Remove empty directories recursively, bottom-up."""
    for path in sorted(directory.rglob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
