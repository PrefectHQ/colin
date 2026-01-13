"""MCP Provider types - separated to avoid circular imports."""

from dataclasses import dataclass, field


@dataclass
class MCPServerConfig:
    """Server configuration for connecting to an MCP server."""

    command: str | None = None
    """Command to run for stdio servers (e.g., 'npx -y @mcp/server')."""

    args: list[str] = field(default_factory=list)
    """Additional arguments for the command."""

    env: dict[str, str] = field(default_factory=dict)
    """Environment variables for the server process."""

    url: str | None = None
    """URL for remote servers."""

    headers: dict[str, str] = field(default_factory=dict)
    """HTTP headers for remote servers."""


@dataclass
class MCPServerInfo:
    """Server metadata from MCP server initialization."""

    name: str
    """Server name."""

    version: str
    """Server version."""

    title: str | None = None
    """Optional human-readable title."""

    instructions: str | None = None
    """Optional instructions describing how to use the server."""

    website_url: str | None = None
    """Optional website URL for this server."""
