"""Project management API functions."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import tomli
import tomli_w
from pydantic import BaseModel, Field, model_validator

from colin.api.manifest import load_manifest
from colin.settings import settings

if TYPE_CHECKING:
    import pathspec

    from colin.output.base import Target

logger = logging.getLogger(__name__)

VarType = Literal["string", "bool", "int", "float", "date", "timestamp"]

# Pattern for ${VAR_NAME} environment variable references
_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _expand_env_vars(value: str) -> str:
    """Expand ${VAR_NAME} patterns in a string with environment variable values.

    Args:
        value: String potentially containing ${VAR_NAME} patterns.

    Returns:
        String with env vars expanded. Unset vars become empty string.
    """

    def replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        return os.environ.get(var_name, "")

    return _ENV_VAR_PATTERN.sub(replace, value)


def _expand_env_vars_recursive(data: Any) -> Any:
    """Recursively expand environment variables in a data structure.

    Processes dicts, lists, and strings. Other types pass through unchanged.

    Args:
        data: Data structure (typically from TOML parsing).

    Returns:
        Same structure with ${VAR_NAME} patterns expanded in strings.
    """
    if isinstance(data, dict):
        return {k: _expand_env_vars_recursive(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_expand_env_vars_recursive(item) for item in data]
    elif isinstance(data, str):
        return _expand_env_vars(data)
    else:
        return data


PROJECT_FILE = "colin.toml"


def create_output_target(
    target_name: str | None = None,
    path: str | None = None,
    **kwargs: Any,
) -> Target:
    """Create an output target instance from config.

    Args:
        target_name: Target name (e.g., "local", "skill", "claude-skill").
            If None, defaults to "local".
        path: Output path (required for "local" and "skill" targets).
        **kwargs: Additional arguments passed to target constructor.

    Returns:
        Configured Target instance.

    Raises:
        ValueError: If target name is unknown or required args missing.
    """
    from colin.output import get_target

    name = target_name or "local"
    target_cls = get_target(name)

    # Build kwargs for constructor
    target_kwargs: dict[str, Any] = {**kwargs}
    if path is not None:
        target_kwargs["path"] = path

    return target_cls(**target_kwargs)


class ProjectOutputConfig(BaseModel):
    """Configuration for project output destination.

    Supports target-based output:
        [project.output]
        target = "claude-skill"
        scope = "user"

    Or simple path-based output (uses LocalTarget):
        [project.output]
        path = "output"
    """

    target: str | None = None
    """Output target name (e.g., 'local', 'skill', 'claude-skill').

    Built-in targets:
    - "local" - writes to specified path (default)
    - "skill" - writes skills to specified path with per-skill manifests
    - "claude-skill" - writes to ~/.claude/skills/ (user) or .claude/skills/ (project)
    """

    path: str | None = None
    """Output path. Required for 'local' and 'skill' targets.
    Optional for 'claude-skill' (overrides default location).
    """

    scope: Literal["user", "project"] | None = None
    """Scope for claude-skill target: 'user' (~/.claude/skills/) or 'project' (.claude/skills/).
    Only used with target='claude-skill'. Defaults to 'user'.
    """

    model_config = {"extra": "allow"}  # Allow additional target-specific kwargs


DEFAULT_CONFIG = """\
# Colin project configuration
# https://github.com/prefecthq/colin

[project]
# Project name (required)
name = "{name}"

# Source directory containing model files (default: "models")
# model-path = "models"

[project.output]
# Output path (default: "output")
path = "output"

# Or use a target for specialized output:
# target = "claude-skill"  # writes to ~/.claude/skills/
# scope = "user"           # or "project" for .claude/skills/

# [vars]
# Project variables accessible via {{{{ colin.var.name }}}}
# Can be overridden with --var name=value or COLIN_VAR_NAME env var
#
# Simple value:
# api_key = "default-value"
#
# Typed with options:
# [vars.timeout]
# type = "int"
# default = 30
# optional = false

# [[providers.mcp]]
# MCP server configurations
# name = "github"
# command = "npx -y @modelcontextprotocol/server-github"
# env = {{ GITHUB_TOKEN = "..." }}
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
    """Provider-specific configuration (with env vars expanded)."""

    raw_config: dict[str, Any] = Field(default_factory=dict)
    """Original configuration before env var expansion (for serialization)."""

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
    id: str | None = None
    """Unique project identifier for manifest ownership claims.

    Format: {name}-{6 random chars}. Generated on init, stable thereafter.
    Used in output manifests to identify which project owns which outputs.
    """
    project_root: Path
    """Absolute path to project directory (where colin.toml lives)."""
    model_path: Path
    """Absolute path to models directory."""
    output_path: Path
    """Absolute path to output directory (published outputs)."""
    manifest_path: Path
    """Absolute path to manifest file (.colin/manifest.json)."""

    # Output configuration
    output: ProjectOutputConfig = Field(default_factory=ProjectOutputConfig)
    """Output destination configuration (plugin, etc.)."""

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


def _parse_providers(
    providers_data: dict[str, Any],
    raw_providers_data: dict[str, Any] | None = None,
) -> dict[str, ProviderInstanceConfig]:
    """Parse [[providers.*]] configuration into ProviderInstanceConfig instances.

    Each provider type uses array-of-table entries:
    - [[providers.s3]] name omitted → schemes ['s3']
    - [[providers.s3]] name = 'dev' → schemes ['s3.dev']
    - [[providers.s3]] schemes = ['s3', 's3.prod'] → explicit schemes

    Args:
        providers_data: Providers section from TOML (with env vars expanded).
        raw_providers_data: Original providers section before env var expansion.
            Used for serialization to avoid leaking secrets.

    Returns:
        Dictionary mapping scheme to ProviderInstanceConfig.
        If multiple instances claim the same scheme, last one wins with a warning.
    """
    if raw_providers_data is None:
        raw_providers_data = providers_data

    result: dict[str, ProviderInstanceConfig] = {}
    defaults_seen: set[str] = set()
    names_seen: dict[str, set[str]] = {}

    for provider_type, value in providers_data.items():
        if not isinstance(value, list):
            raise ValueError(
                f"[providers.{provider_type}] must use array-of-tables "
                f"([[providers.{provider_type}]])"
            )

        raw_entries = raw_providers_data.get(provider_type, [])

        for idx, entry in enumerate(value):
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

            # Get raw config for serialization (preserves ${VAR} patterns)
            raw_entry = raw_entries[idx] if idx < len(raw_entries) else entry
            raw_config = {
                key: val for key, val in raw_entry.items() if key not in {"name", "schemes"}
            }

            instance = ProviderInstanceConfig(
                provider_type=provider_type,
                name=name,
                schemes=schemes,
                config=config,
                raw_config=raw_config,
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

    # Keep raw providers data before expansion (for serialization without leaking secrets)
    raw_providers_data = data.get("providers", {})

    # Expand ${VAR_NAME} patterns with environment variable values
    data = _expand_env_vars_recursive(data)

    if "mcp" in data:
        raise ValueError("MCP servers must be configured under [[providers.mcp]]")

    project = data.get("project", {})
    # Resolve paths relative to project root (or use absolute if specified)
    project_root = path.parent.resolve()
    model_path_rel = project.get("model-path", "models")
    manifest_path_rel = project.get("manifest-path")

    # Handle absolute paths for model-path
    if Path(model_path_rel).is_absolute():
        model_path = Path(model_path_rel).resolve()
    else:
        model_path = (project_root / model_path_rel).resolve()

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
    providers = _parse_providers(providers_data, raw_providers_data)

    # Parse project variables
    vars_data = data.get("vars", {})
    vars_config = _parse_vars(vars_data)

    # Parse output configuration from [project.output]
    output_data = project.get("output", {})
    output_config = ProjectOutputConfig.model_validate(output_data)

    # Build target kwargs from config
    target_kwargs: dict[str, Any] = {}
    # Default to path = "output" if no target or path specified
    if output_config.path:
        target_kwargs["path"] = output_config.path
    elif not output_config.target:
        target_kwargs["path"] = "output"  # Default output path
    if output_config.scope:
        target_kwargs["scope"] = output_config.scope
    # Include any extra kwargs from config
    if output_config.model_extra:
        for key, value in output_config.model_extra.items():
            target_kwargs[key] = value

    target = create_output_target(output_config.target, **target_kwargs)
    output_path = target.resolve_path(project_root)

    # Get project name and ID
    project_name = project.get("name", "colin-project")
    project_id = project.get("id")

    return ProjectConfig(
        name=project_name,
        id=project_id,
        project_root=project_root,
        model_path=model_path,
        output_path=output_path,
        manifest_path=manifest_path,
        output=output_config,
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

    project_data: dict[str, Any] = {
        "name": config.name,
        "model-path": str(model_path_rel),
    }

    # Add project ID if set
    if config.id:
        project_data["id"] = config.id

    # Add output config
    output_data: dict[str, Any] = {}
    if config.output.target:
        output_data["target"] = config.output.target
    if config.output.path:
        output_data["path"] = config.output.path
    elif not config.output.target:
        # No target specified, save the resolved path
        try:
            output_path_rel = config.output_path.relative_to(config.project_root)
            output_data["path"] = str(output_path_rel)
        except ValueError:
            output_data["path"] = str(config.output_path)
    if config.output.scope:
        output_data["scope"] = config.output.scope
    if output_data:
        project_data["output"] = output_data

    data: dict[str, Any] = {"project": project_data}

    providers_data: dict[str, list[dict[str, Any]]] = {}
    for instance in config.providers.values():
        # Use raw_config to preserve ${VAR} patterns and avoid leaking secrets
        entry = dict(instance.raw_config) if instance.raw_config else dict(instance.config)
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


def _load_output_manifest(manifest_path: Path) -> dict[str, Any] | None:
    """Load an output manifest file.

    Args:
        manifest_path: Path to .colin-manifest.json.

    Returns:
        Parsed manifest dict or None if not found/invalid.
    """
    if not manifest_path.exists():
        return None
    try:
        return json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def get_stale_files(
    config: ProjectConfig,
    include_compiled: bool = False,
) -> list[Path]:
    """Find stale files in output/ (and optionally .colin/compiled/).

    For output/, uses .colin-manifest.json files to track what files belong.
    Each manifest defines its scope - files not in any manifest are stale.

    For .colin/compiled/, uses the internal manifest.json.

    Args:
        config: Project configuration.
        include_compiled: If True, also check .colin/compiled/ for stale files.

    Returns:
        List of absolute paths to stale files, sorted alphabetically.
    """
    output_dir = config.output_path
    compiled_dir = config.build_path / "compiled"
    internal_manifest = load_manifest(config.manifest_path)

    stale: list[Path] = []

    # Check output/ for stale files using output manifests
    # Filter by project_name to avoid affecting other projects in shared directories
    if output_dir.exists():
        stale.extend(_get_stale_from_output_manifests(output_dir, project_name=config.name))

    # Optionally check .colin/compiled/ for stale files (uses internal manifest)
    if include_compiled and compiled_dir.exists():
        # Get all output paths from internal manifest
        all_output_paths: set[str] = set()
        for doc in internal_manifest.documents.values():
            if doc.output_path:
                all_output_paths.add(doc.output_path)
            for file_path in doc.file_outputs:
                all_output_paths.add(file_path)

        for path in compiled_dir.rglob("*"):
            if path.is_file():
                try:
                    rel_path = str(path.relative_to(compiled_dir))
                    if rel_path not in all_output_paths:
                        stale.append(path)
                except ValueError:
                    stale.append(path)

    return sorted(stale)


# Files to never consider stale (system files, editor files, etc.)
DEFAULT_IGNORED_FILES = {
    ".DS_Store",
    ".gitignore",
    ".gitkeep",
    ".colinignore",
    "Thumbs.db",
    "desktop.ini",
}


def _load_colinignore(directory: Path) -> pathspec.PathSpec | None:
    """Load .colinignore file from directory if it exists.

    Args:
        directory: Directory to check for .colinignore.

    Returns:
        PathSpec object for matching, or None if no .colinignore exists.
    """
    import pathspec

    ignore_file = directory / ".colinignore"
    if not ignore_file.exists():
        return None

    try:
        patterns = ignore_file.read_text().splitlines()
        return pathspec.PathSpec.from_lines("gitwildmatch", patterns)
    except OSError:
        return None


def _is_ignored_file(path: Path, scope_dir: Path | None = None) -> bool:
    """Check if a file should be ignored for stale detection.

    Args:
        path: File path to check.
        scope_dir: Directory containing the manifest (for .colinignore lookup).

    Returns:
        True if file should be ignored.
    """
    # Always ignore system files
    if path.name in DEFAULT_IGNORED_FILES:
        return True

    # Check .colinignore if scope_dir provided
    if scope_dir is not None:
        ignore_spec = _load_colinignore(scope_dir)
        if ignore_spec is not None:
            try:
                rel_path = path.relative_to(scope_dir)
                if ignore_spec.match_file(str(rel_path)):
                    return True
            except ValueError:
                pass  # Path not relative to scope_dir

    return False


def _get_stale_from_output_manifests(
    output_dir: Path,
    project_name: str | None = None,
) -> list[Path]:
    """Find stale files in output directory using output manifests.

    Scans for .colin-manifest.json files. Each manifest defines what files
    belong in its directory scope. Subdirectories are only considered stale
    if they are tracked by the manifest (have files listed).

    Args:
        output_dir: Output directory to scan.
        project_name: If provided, only consider manifests belonging to this project.
            Used for project-scoped cleaning to avoid affecting other projects
            in shared output directories.

    Returns:
        List of stale file paths.
    """
    stale: list[Path] = []

    # Find all output manifests
    for manifest_path in output_dir.rglob(".colin-manifest.json"):
        manifest_data = _load_output_manifest(manifest_path)
        if manifest_data is None:
            continue

        # If project_name filter is set, skip manifests from other projects
        if project_name is not None:
            manifest_project_name = manifest_data.get("project_name")
            if manifest_project_name != project_name:
                continue

        # This manifest owns its directory - check for stale files
        scope_dir = manifest_path.parent
        manifest_files = set(manifest_data.get("files", {}).keys())

        for path in scope_dir.iterdir():
            if path.is_file() and path.name != ".colin-manifest.json":
                if not _is_ignored_file(path, scope_dir) and path.name not in manifest_files:
                    stale.append(path)
            elif path.is_dir():
                # Skip subdirs with their own manifests entirely
                subdir_manifest = path / ".colin-manifest.json"
                if subdir_manifest.exists():
                    continue  # Has its own manifest, will be handled separately

                # Only recurse into subdirs that we own (have files listed in manifest)
                subdir_name = path.name
                has_tracked_files = any(f.startswith(f"{subdir_name}/") for f in manifest_files)
                if has_tracked_files:
                    # We own this subdir - check for stale files
                    for subpath in path.rglob("*"):
                        if subpath.is_file() and not _is_ignored_file(subpath, scope_dir):
                            rel_path = str(subpath.relative_to(scope_dir))
                            if rel_path not in manifest_files:
                                stale.append(subpath)

    return stale


def get_stale_files_by_project(output_dir: Path) -> dict[str, list[Path]]:
    """Find stale files in output directory, grouped by project name.

    Scans for .colin-manifest.json files and returns stale files organized
    by the project name from each manifest. Each manifest only controls its
    immediate directory - subdirectories with their own manifests are separate.

    Args:
        output_dir: Output directory to scan.

    Returns:
        Dict mapping project name to list of stale file paths.
    """
    if not output_dir.exists():
        return {}

    result: dict[str, list[Path]] = {}

    for manifest_path in output_dir.rglob(".colin-manifest.json"):
        manifest_data = _load_output_manifest(manifest_path)
        if manifest_data is None:
            continue

        # Get project name from manifest (fall back to directory name)
        project_name = manifest_data.get("project_name")
        if not project_name:
            # Try to get from project_config path
            project_config = manifest_data.get("project_config")
            if project_config:
                project_name = Path(project_config).parent.name
            else:
                project_name = manifest_path.parent.name

        scope_dir = manifest_path.parent
        manifest_files = set(manifest_data.get("files", {}).keys())
        stale: list[Path] = []

        # Only check files directly in this manifest's directory
        # Subdirectories are only checked if they don't have their own manifest
        # AND are listed in this manifest's files (i.e., we created them)
        for path in scope_dir.iterdir():
            if path.is_file() and path.name != ".colin-manifest.json":
                if not _is_ignored_file(path, scope_dir) and path.name not in manifest_files:
                    stale.append(path)
            elif path.is_dir():
                # Only recurse into subdirs that we own (have files listed in manifest)
                # Skip subdirs with their own manifests entirely
                subdir_manifest = path / ".colin-manifest.json"
                if subdir_manifest.exists():
                    continue  # Has its own manifest, will be handled separately

                # Check if any files in this subdir are tracked by our manifest
                subdir_name = path.name
                has_tracked_files = any(f.startswith(f"{subdir_name}/") for f in manifest_files)
                if has_tracked_files:
                    # We own this subdir - check for stale files
                    for subpath in path.rglob("*"):
                        if subpath.is_file() and not _is_ignored_file(subpath, scope_dir):
                            rel_path = str(subpath.relative_to(scope_dir))
                            if rel_path not in manifest_files:
                                stale.append(subpath)

        if stale:
            if project_name in result:
                result[project_name].extend(stale)
            else:
                result[project_name] = stale

    return result


def clean_project(config: ProjectConfig, all: bool = False) -> list[Path]:
    """Remove stale files from the project.

    Uses output manifests (.colin-manifest.json) for ownership tracking in the
    output directory. Only cleans files in directories owned by this project.

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

    # Clean up empty directories and stale manifests
    if config.output_path.exists():
        _remove_empty_dirs(config.output_path)
        _cleanup_empty_manifests(config.output_path)
    if all:
        compiled_dir = config.build_path / "compiled"
        if compiled_dir.exists():
            _remove_empty_dirs(compiled_dir)

    return sorted(removed)


def get_stale_files_from_output(output_dir: Path) -> list[Path]:
    """Find stale files in an output directory using its manifests.

    Works standalone without needing a project config. Each manifest
    defines what files belong in its directory scope.

    Args:
        output_dir: Output directory to scan for stale files.

    Returns:
        List of absolute paths to stale files, sorted alphabetically.
    """
    if not output_dir.exists():
        return []
    return sorted(_get_stale_from_output_manifests(output_dir))


def clean_output_directory(output_dir: Path) -> list[Path]:
    """Remove stale files from an output directory.

    Works standalone without needing a project config. Uses manifests
    in the directory to determine what files belong.

    Args:
        output_dir: Output directory to clean.

    Returns:
        List of paths that were removed.
    """
    stale_files = get_stale_files_from_output(output_dir)
    removed: list[Path] = []

    for path in stale_files:
        path.unlink()
        removed.append(path)

    # Clean up empty directories and empty manifests
    if output_dir.exists():
        _remove_empty_dirs(output_dir)
        _cleanup_empty_manifests(output_dir)

    return sorted(removed)


def _remove_empty_dirs(directory: Path) -> None:
    """Remove empty directories recursively, bottom-up."""
    for path in sorted(directory.rglob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()


def _cleanup_empty_manifests(output_dir: Path) -> None:
    """Remove manifests for directories that are now empty (except manifest).

    Also removes the directory if only the manifest remains.

    Args:
        output_dir: Output directory to scan.
    """
    for manifest_path in sorted(output_dir.rglob(".colin-manifest.json"), reverse=True):
        manifest_data = _load_output_manifest(manifest_path)
        if manifest_data is None:
            continue

        # Check if directory is empty except for manifest
        scope_dir = manifest_path.parent
        remaining = [f for f in scope_dir.iterdir() if f.name != ".colin-manifest.json"]
        if not remaining:
            # Remove manifest and directory if it's not the output root
            manifest_path.unlink()
            if scope_dir != output_dir:
                try:
                    scope_dir.rmdir()
                except OSError:
                    pass  # Directory not empty (maybe another process added files)
