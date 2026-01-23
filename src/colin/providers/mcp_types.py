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


@dataclass
class MCPResourceInfo:
    """Lightweight resource info from list_resources()."""

    uri: str
    """Full MCP resource URI."""

    name: str | None = None
    """Resource name."""

    description: str | None = None
    """Optional description from server."""

    mime_type: str | None = None
    """MIME type of the resource content."""


@dataclass
class SkillFileInfo:
    """A file within a skill."""

    path: str
    """Relative path within the skill (e.g., 'SKILL.md', 'tools/deploy.md')."""

    hash: str | None = None
    """SHA256 hash for change detection."""


@dataclass
class SkillInfo:
    """Skill discovered from MCP server via skill:// scheme."""

    name: str
    """Skill identifier (from skill://{name}/...)."""

    description: str | None = None
    """Skill description from SKILL.md resource."""

    files: list[SkillFileInfo] = field(default_factory=list)
    """Files in this skill from manifest."""
