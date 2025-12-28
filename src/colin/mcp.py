"""MCP client manager for Colin."""

from __future__ import annotations

from fastmcp import Client
from fastmcp.mcp_config import MCPConfig


class MCPManager:
    """Manages lazy connections to MCP servers."""

    def __init__(self, mcp_config: MCPConfig) -> None:
        """Initialize the MCP manager.

        Args:
            mcp_config: FastMCP configuration with server definitions.
        """
        self._config = mcp_config
        self._clients: dict[str, Client] = {}

    async def _get_client(self, name: str) -> Client:
        """Get or create a client for the named server.

        Args:
            name: Server name.

        Returns:
            Connected Client instance.

        Raises:
            ValueError: If server not found.
        """
        if name not in self._clients:
            if name not in self._config.mcpServers:
                raise ValueError(f"Unknown MCP server: {name}")

            # Create single-server config for this client
            server_config = MCPConfig(mcpServers={name: self._config.mcpServers[name]})
            client = Client(server_config)
            await client.__aenter__()
            self._clients[name] = client

        return self._clients[name]

    async def read_resource(self, server: str, uri: str) -> str:
        """Read a resource from an MCP server.

        Args:
            server: Server name.
            uri: Resource URI.

        Returns:
            Resource content as string.
        """
        client = await self._get_client(server)
        contents = await client.read_resource(uri)
        # FastMCP returns a list of content items
        if contents:
            return contents[0].text or ""
        return ""

    async def get_prompt(
        self, server: str, name: str, arguments: dict[str, str] | None = None
    ) -> str:
        """Get a prompt from an MCP server.

        Args:
            server: Server name.
            name: Prompt name.
            arguments: Optional prompt arguments.

        Returns:
            Rendered prompt content as string.
        """
        client = await self._get_client(server)
        result = await client.get_prompt(name, arguments or {})
        # Extract text content from prompt messages
        parts = []
        for msg in result.messages:
            if hasattr(msg.content, "text"):
                parts.append(msg.content.text)
        return "\n".join(parts)

    async def close(self) -> None:
        """Close all connected clients."""
        for client in self._clients.values():
            await client.__aexit__(None, None, None)
        self._clients.clear()
