"""Project management API functions."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import tomli
import tomli_w
from fastmcp.mcp_config import MCPConfig, RemoteMCPServer, StdioMCPServer
from pydantic import BaseModel, Field

from colin.api.manifest import load_manifest
from colin.settings import settings

PROJECT_FILE = "colin.toml"

DEFAULT_CONFIG = """\
# Colin project configuration
# https://github.com/prefecthq/colin

[project]
name = "{name}"

# model-path = "models"
# target-path = "target"
"""


class StorageConfig(BaseModel):
    """Configuration for project or artifacts storage."""

    provider: str = "file"
    config: dict[str, Any] = Field(default_factory=dict)


class ProviderInstanceConfig(BaseModel):
    """Configuration for a provider instance."""

    provider_type: str
    """Provider type name (e.g., 's3', 'mcp')."""

    instance_name: str | None = None
    """Instance name if specified (e.g., 'dev' for [providers.s3.dev])."""

    config: dict[str, Any] = Field(default_factory=dict)
    """Provider-specific configuration."""

    @property
    def scheme(self) -> str:
        """Derived URI scheme (e.g., 's3' or 's3-dev')."""
        if self.instance_name:
            return f"{self.provider_type}-{self.instance_name}"
        return self.provider_type


class ProjectConfig(BaseModel):
    """Colin project configuration with resolved paths.

    All paths are absolute and resolved at load time.
    """

    name: str = "colin-project"
    project_root: Path
    """Absolute path to project directory (where colin.toml lives)."""
    model_path: Path
    """Absolute path to models directory."""
    target_path: Path
    """Absolute path to target directory."""
    manifest_path: Path
    """Absolute path to manifest file."""
    default_llm_model: str | None = None
    mcp: MCPConfig = MCPConfig()

    # Provider configuration
    project_storage: StorageConfig = Field(default_factory=StorageConfig)
    artifacts_storage: StorageConfig | None = None
    providers: dict[str, ProviderInstanceConfig] = Field(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}


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
    """Parse [providers.*] configuration into ProviderInstanceConfig instances.

    Handles both:
    - [providers.s3] → scheme 's3'
    - [providers.s3.dev] → scheme 's3-dev'

    Args:
        providers_data: Raw providers section from TOML.

    Returns:
        Dictionary mapping scheme to ProviderInstanceConfig.
    """
    result: dict[str, ProviderInstanceConfig] = {}

    for provider_type, value in providers_data.items():
        if isinstance(value, dict):
            # Check if this is a provider config or nested instances
            # If all values are dicts, it's nested instances like [providers.s3.dev]
            # If any value is not a dict, it's a direct config like [providers.s3]
            has_nested = all(isinstance(v, dict) for v in value.values()) and value
            has_direct = any(not isinstance(v, dict) for v in value.values())

            if has_direct or not value:
                # Direct config: [providers.s3] bucket = "..."
                instance = ProviderInstanceConfig(
                    provider_type=provider_type,
                    instance_name=None,
                    config=value,
                )
                result[instance.scheme] = instance
            elif has_nested:
                # Nested instances: [providers.s3.dev] and [providers.s3.prod]
                for instance_name, instance_config in value.items():
                    if isinstance(instance_config, dict):
                        instance = ProviderInstanceConfig(
                            provider_type=provider_type,
                            instance_name=instance_name,
                            config=instance_config,
                        )
                        result[instance.scheme] = instance

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

    project = data.get("project", {})
    mcp_data = data.get("mcp", {})
    servers_data = mcp_data.get("servers", {})

    # Resolve paths relative to project root
    project_root = path.parent.resolve()
    model_path_rel = project.get("model-path", "models")
    target_path_rel = project.get("target-path", "target")
    manifest_path_rel = project.get("manifest-path")

    model_path = (project_root / model_path_rel).resolve()
    target_path = (project_root / target_path_rel).resolve()

    # Manifest path: explicit config or default to {target}/manifest.json
    if manifest_path_rel:
        manifest_path = (project_root / manifest_path_rel).resolve()
    else:
        manifest_path = target_path / settings.manifest_file

    # Convert [mcp.servers.name] format to MCPConfig
    mcp_servers: dict[str, StdioMCPServer | RemoteMCPServer] = {}
    for name, server_data in servers_data.items():
        if "url" in server_data:
            mcp_servers[name] = RemoteMCPServer(
                url=server_data["url"],
                headers=server_data.get("headers", {}),
            )
        elif "command" in server_data:
            mcp_servers[name] = StdioMCPServer(
                command=server_data["command"],
                args=server_data.get("args", []),
                env=server_data.get("env", {}),
            )

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

    return ProjectConfig(
        name=project.get("name", "colin-project"),
        project_root=project_root,
        model_path=model_path,
        target_path=target_path,
        manifest_path=manifest_path,
        default_llm_model=project.get("default-llm-model"),
        mcp=MCPConfig(mcpServers=mcp_servers),
        project_storage=project_storage,
        artifacts_storage=artifacts_storage,
        providers=providers,
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
    target_path_rel: str = "target",
) -> tuple[Path, Path]:
    """Initialize a new Colin project with colin.toml and models directory.

    Args:
        directory: Directory to create project in.
        name: Project name (default: directory name).
        model_path_rel: Relative path to models directory (default: "models").
        target_path_rel: Relative path to target directory (default: "target").

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
    target_path = (project_root / target_path_rel).resolve()
    manifest_path = target_path / settings.manifest_file

    # Create colin.toml with full config
    project_name = name or directory.name
    config = ProjectConfig(
        name=project_name,
        project_root=project_root,
        model_path=model_path,
        target_path=target_path,
        manifest_path=manifest_path,
    )
    # Create project directory and models subdirectory
    model_path.mkdir(parents=True, exist_ok=True)

    save_project(project_file, config)

    return project_file, model_path


def save_project(path: Path, config: ProjectConfig) -> None:
    """Save project configuration to colin.toml.

    Converts absolute paths back to relative paths for serialization.

    Args:
        path: Path to colin.toml file.
        config: Configuration to save.
    """
    # Convert absolute paths to relative for TOML
    model_path_rel = config.model_path.relative_to(config.project_root)
    target_path_rel = config.target_path.relative_to(config.project_root)

    project_data: dict[str, Any] = {
        "name": config.name,
        "model-path": str(model_path_rel),
        "target-path": str(target_path_rel),
    }
    if config.default_llm_model:
        project_data["default-llm-model"] = config.default_llm_model

    data: dict[str, Any] = {"project": project_data}

    # Convert MCPConfig to [mcp.servers.name] format
    if config.mcp.mcpServers:
        servers = {}
        for name, server in config.mcp.mcpServers.items():
            servers[name] = server.model_dump(exclude_none=True, exclude_defaults=True)
        data["mcp"] = {"servers": servers}

    with open(path, "wb") as f:
        tomli_w.dump(data, f)


def get_project_status(project_dir: Path) -> dict:
    """Get status information for a project.

    Args:
        project_dir: Project directory.

    Returns:
        Dictionary with status information:
        - project_file: Path to colin.toml (or None if not found)
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
        target_dir = config.target_path
        manifest_path = config.manifest_path
    else:
        project_dir = project_dir.resolve()
        project_name = project_dir.name
        target_dir = project_dir / "target"
        manifest_path = target_dir / settings.manifest_file

    manifest = load_manifest(manifest_path)

    total_llm_calls = sum(len(doc.llm_calls) for doc in manifest.documents.values())
    total_cost = sum(doc.total_cost_usd for doc in manifest.documents.values())

    return {
        "project_file": project_file,
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
        target_dir = config.target_path
    else:
        target_dir = project_dir.resolve() / "target"

    if not target_dir.exists():
        return []

    # Collect files before removal
    removed_files = [path for path in target_dir.rglob("*") if path.is_file()]

    # Remove directory
    shutil.rmtree(target_dir)

    return removed_files
