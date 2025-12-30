"""MCP Provider - Model Context Protocol integration.

Provides a read-only provider for mcp-{instance}:// URIs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlparse

from fastmcp import Client
from fastmcp.mcp_config import MCPConfig, RemoteMCPServer, StdioMCPServer

from colin.models import RefResult
from colin.providers.base import Provider


def build_mcp_uri(
    scheme: str, resource: str | None = None, prompt: str | None = None, **kwargs: str
) -> str:
    """Build an MCP URI.

    Args:
        scheme: MCP scheme (e.g., 'mcp-linear').
        resource: Resource URI to fetch.
        prompt: Prompt name to invoke.
        **kwargs: Additional prompt arguments.

    Returns:
        Formatted MCP URI.
    """
    params: dict[str, str] = {}
    if resource:
        params["resource"] = resource
    elif prompt:
        params["prompt"] = prompt
        params.update(kwargs)

    return f"{scheme}://?{urlencode(params)}"


class MCPProvider(Provider):
    """Read-only provider for MCP server integration.

    Each MCP server instance becomes a provider with scheme mcp-{name}.

    URI format: mcp-{instance}://?resource=<url-encoded-uri>
    or: mcp-{instance}://?prompt=<name>&arg1=val1&arg2=val2
    """

    def __init__(self, instance: str, server: StdioMCPServer | RemoteMCPServer) -> None:
        """Initialize MCP provider for a specific server.

        Args:
            instance: Server name (e.g., 'linear' for [providers.mcp.linear]).
            server: MCP server configuration.

        Raises:
            ValueError: If instance is not provided.
        """
        if not instance:
            raise ValueError(
                "MCP provider requires an instance name (e.g., [providers.mcp.linear])"
            )

        self.scheme = f"mcp-{instance}"
        self._instance = instance
        self._server = server

        mcp_config = MCPConfig(mcpServers={instance: server})
        self._client = Client(mcp_config)

    async def read(self, path: str) -> str:
        """Read content from an MCP resource or prompt.

        Args:
            path: URI in format mcp-{instance}://?resource=<uri> or ?prompt=<name>

        Returns:
            Content as string.

        Raises:
            ValueError: If URI format is invalid.
        """
        parsed = urlparse(path)
        query = parse_qs(parsed.query)

        if "resource" in query:
            resource_uri = query["resource"][0]
            return await self._read_resource(resource_uri)

        elif "prompt" in query:
            prompt_name = query["prompt"][0]
            # All other query params are prompt arguments
            args = {k: v[0] for k, v in query.items() if k != "prompt"}
            return await self._get_prompt(prompt_name, args)

        else:
            raise ValueError(f"Invalid MCP URI: {path}. Expected ?resource=<uri> or ?prompt=<name>")

    async def _read_resource(self, resource_uri: str) -> str:
        """Read a resource from the MCP server."""
        contents = await self._client.read_resource(resource_uri)
        if contents:
            return contents[0].text or ""
        return ""

    async def _get_prompt(self, name: str, arguments: dict[str, str]) -> str:
        """Get a prompt from the MCP server."""
        result = await self._client.get_prompt(name, arguments)
        parts = []
        for msg in result.messages:
            if hasattr(msg.content, "text"):
                parts.append(msg.content.text)
        return "\n".join(parts)

    async def mcp_resource(self, resource_uri: str) -> RefResult:
        """Fetch an MCP resource.

        Template function for accessing MCP resources.

        Args:
            resource_uri: MCP resource URI.

        Returns:
            RefResult with content.
        """
        content = await self._read_resource(resource_uri)
        full_uri = build_mcp_uri(self.scheme, resource=resource_uri)
        return RefResult(
            name=resource_uri.split("/")[-1],
            description=None,
            content=content,
            template="",
            updated=datetime.now(timezone.utc),
            uri=full_uri,
        )

    async def mcp_prompt(self, name: str, **arguments: str) -> RefResult:
        """Get an MCP prompt.

        Template function for accessing MCP prompts.

        Args:
            name: Prompt name.
            **arguments: Prompt arguments.

        Returns:
            RefResult with content.
        """
        content = await self._get_prompt(name, arguments)
        full_uri = build_mcp_uri(self.scheme, prompt=name, **arguments)
        return RefResult(
            name=name,
            description=None,
            content=content,
            template="",
            updated=datetime.now(timezone.utc),
            uri=full_uri,
        )
