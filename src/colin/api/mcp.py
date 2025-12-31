"""MCP server management API functions."""

from pathlib import Path
from typing import Any

from fastmcp.mcp_config import RemoteMCPServer, StdioMCPServer

from colin.api.project import (
    ProviderInstanceConfig,
    find_project_file,
    load_project,
    save_project,
)


def _build_mcp_server(config: dict[str, Any]) -> StdioMCPServer | RemoteMCPServer:
    """Build an MCP server config from provider config."""
    if "url" in config:
        return RemoteMCPServer(
            url=str(config["url"]),
            headers=config.get("headers", {}),
        )
    if "command" in config:
        return StdioMCPServer(
            command=str(config["command"]),
            args=config.get("args", []),
            env=config.get("env", {}),
        )
    raise ValueError("MCP server config requires 'command' or 'url'")


def add_server(
    project_dir: Path,
    name: str,
    server: StdioMCPServer | RemoteMCPServer,
) -> None:
    """Add an MCP server to colin.toml.

    Args:
        project_dir: Project directory.
        name: Server name.
        server: FastMCP server configuration (StdioMCPServer or RemoteMCPServer).

    Raises:
        FileNotFoundError: If no colin.toml found.
        ValueError: If server with name already exists.
    """
    project_file = find_project_file(project_dir.resolve())
    if not project_file:
        raise FileNotFoundError(f"No colin.toml found in {project_dir}")

    config = load_project(project_file)

    for instance in config.providers.values():
        if instance.provider_type == "mcp" and instance.name == name:
            raise ValueError(f"MCP server '{name}' already exists")

    instance = ProviderInstanceConfig(
        provider_type="mcp",
        name=name,
        config=server.model_dump(exclude_none=True, exclude_defaults=True),
    )
    # Register under the first scheme (default is mcp.{name})
    for scheme in instance.get_schemes():
        config.providers[scheme] = instance
    save_project(project_file, config)


def remove_server(project_dir: Path, name: str) -> None:
    """Remove an MCP server from colin.toml.

    Args:
        project_dir: Project directory.
        name: Server name to remove.

    Raises:
        FileNotFoundError: If no colin.toml found.
        ValueError: If server not found.
    """
    project_file = find_project_file(project_dir.resolve())
    if not project_file:
        raise FileNotFoundError(f"No colin.toml found in {project_dir}")

    config = load_project(project_file)

    to_delete: str | None = None
    for scheme, instance in config.providers.items():
        if instance.provider_type == "mcp" and instance.name == name:
            to_delete = scheme
            break

    if to_delete is None:
        raise ValueError(f"MCP server '{name}' not found")

    del config.providers[to_delete]
    save_project(project_file, config)


def list_servers(project_dir: Path) -> dict[str, StdioMCPServer | RemoteMCPServer]:
    """Get configured MCP servers.

    Args:
        project_dir: Project directory.

    Returns:
        Mapping of server name to MCP server configuration.

    Raises:
        FileNotFoundError: If no colin.toml found.
    """
    project_file = find_project_file(project_dir.resolve())
    if not project_file:
        raise FileNotFoundError(f"No colin.toml found in {project_dir}")

    config = load_project(project_file)
    servers: dict[str, StdioMCPServer | RemoteMCPServer] = {}
    for instance in config.providers.values():
        if instance.provider_type != "mcp" or instance.name is None:
            continue
        servers[instance.name] = _build_mcp_server(instance.config)
    return servers
