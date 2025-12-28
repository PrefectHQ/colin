"""MCP server management API functions."""

from pathlib import Path

from fastmcp.mcp_config import MCPConfig, RemoteMCPServer, StdioMCPServer

from colin.api.project import find_project_file, load_project, save_project


def add_server(
    project_dir: Path,
    name: str,
    *,
    url: str | None = None,
    command: str | None = None,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> None:
    """Add an MCP server to colin.toml.

    Args:
        project_dir: Project directory.
        name: Server name.
        url: Server URL for HTTP/SSE transport.
        command: Command for stdio transport.
        args: Arguments for stdio command.
        env: Environment variables for the server.

    Raises:
        FileNotFoundError: If no colin.toml found.
        ValueError: If server with name already exists.
    """
    project_file = find_project_file(project_dir.resolve())
    if not project_file:
        raise FileNotFoundError(f"No colin.toml found in {project_dir}")

    config = load_project(project_file)

    # Check for duplicate
    if name in config.mcp.mcpServers:
        raise ValueError(f"MCP server '{name}' already exists")

    # Create server config
    if url:
        server: StdioMCPServer | RemoteMCPServer = RemoteMCPServer(url=url)
    elif command:
        server = StdioMCPServer(command=command, args=args or [], env=env or {})
    else:
        raise ValueError("Either url or command must be provided")

    config.mcp.mcpServers[name] = server
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

    if name not in config.mcp.mcpServers:
        raise ValueError(f"MCP server '{name}' not found")

    del config.mcp.mcpServers[name]
    save_project(project_file, config)


def list_servers(project_dir: Path) -> MCPConfig:
    """Get configured MCP servers.

    Args:
        project_dir: Project directory.

    Returns:
        MCPConfig with server configurations.

    Raises:
        FileNotFoundError: If no colin.toml found.
    """
    project_file = find_project_file(project_dir.resolve())
    if not project_file:
        raise FileNotFoundError(f"No colin.toml found in {project_dir}")

    config = load_project(project_file)
    return config.mcp
