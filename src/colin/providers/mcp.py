"""MCP Provider - Model Context Protocol integration.

Provides a read-only provider for mcp:// and mcp.{instance}:// URIs.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlencode, urlparse

from fastmcp import Client
from fastmcp.mcp_config import MCPConfig, RemoteMCPServer, StdioMCPServer

from colin.api.project import ProviderInstanceConfig
from colin.providers.base import Provider
from colin.providers.context import ProviderContext

if TYPE_CHECKING:
    from colin.models import RefResult


@dataclass
class MCPResource:
    """Domain object returned by mcp.resource()."""

    uri: str
    content: str
    name: str
    description: str | None = None
    updated: datetime | None = None

    @property
    def last_updated(self) -> datetime:
        """When this resource was last modified."""
        return self.updated or datetime.now(timezone.utc)

    def to_ref_result(self) -> RefResult:
        """Convert to RefResult for dependency tracking."""
        from colin.models import RefResult

        return RefResult(
            name=self.name,
            description=self.description,
            content=self.content,
            template="",
            updated=self.last_updated,
            uri=self.uri,
            source=self,
        )


@dataclass
class MCPPrompt:
    """Domain object returned by mcp.prompt()."""

    uri: str
    content: str
    name: str
    description: str | None = None
    updated: datetime | None = None

    @property
    def last_updated(self) -> datetime:
        """When this prompt was last retrieved."""
        return self.updated or datetime.now(timezone.utc)

    def to_ref_result(self) -> RefResult:
        """Convert to RefResult for dependency tracking."""
        from colin.models import RefResult

        return RefResult(
            name=self.name,
            description=self.description,
            content=self.content,
            template="",
            updated=self.last_updated,
            uri=self.uri,
            source=self,
        )


def build_mcp_uri(
    scheme: str, resource: str | None = None, prompt: str | None = None, **kwargs: str
) -> str:
    """Build an MCP URI.

    Args:
        scheme: MCP scheme (e.g., 'mcp.github' or 'mcp').
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


def _strip_scheme(uri: str) -> str:
    """Strip URI scheme prefix for cleaner display."""
    if "://" in uri:
        return uri.split("://", 1)[1]
    return uri


def create_mcp_provider(config: ProviderInstanceConfig) -> MCPProvider:
    """Create an MCP provider from a provider config."""
    data = config.config
    if "url" in data:
        server: StdioMCPServer | RemoteMCPServer = RemoteMCPServer(
            url=str(data["url"]),
            headers=data.get("headers", {}),
        )
    elif "command" in data:
        server = StdioMCPServer(
            command=str(data["command"]),
            args=data.get("args", []),
            env=data.get("env", {}),
        )
    else:
        raise ValueError("MCP provider requires 'command' or 'url' config")
    return MCPProvider(config.name, server, scheme=config.scheme)


class MCPProvider(Provider):
    """Read-only provider for MCP server integration.

    Each MCP server instance becomes a provider with scheme mcp.{name}.

    URI format: mcp://?resource=<url-encoded-uri> (default instance)
    or: mcp.{instance}://?resource=<url-encoded-uri>
    or: mcp.{instance}://?prompt=<name>&arg1=val1&arg2=val2
    """

    def __init__(
        self,
        instance: str | None,
        server: StdioMCPServer | RemoteMCPServer,
        scheme: str | None = None,
    ) -> None:
        """Initialize MCP provider for a specific server.

        Args:
            instance: Server name (e.g., 'linear' for [[providers.mcp.linear]]).
            server: MCP server configuration.
            scheme: Override scheme for URI routing.
        """
        if instance is not None and not instance.strip():
            raise ValueError("MCP provider requires an instance name")

        self._instance = instance or "default"
        self._server = server
        provider_scheme = scheme or (f"mcp.{instance}" if instance else "mcp")
        self.schemes = [provider_scheme]
        self.namespace = "mcp"
        self._client: Client | None = None

    async def _get_client(self) -> Client:
        """Get or create an MCP client for this provider."""
        if self._client is None:
            mcp_config = MCPConfig(mcpServers={self._instance: self._server})
            client = Client(mcp_config)
            await client.__aenter__()
            self._client = client
        return self._client

    async def close(self) -> None:
        """Close the MCP client if open."""
        if self._client is not None:
            await self._client.__aexit__(None, None, None)
            self._client = None

    async def read(self, uri: str) -> str:
        """Read content from an MCP resource or prompt.

        Args:
            uri: Full URI in format mcp.x://?resource=<uri> or mcp.x://?prompt=<name>

        Returns:
            Content as string.

        Raises:
            ValueError: If URI format is invalid.
        """
        parsed = urlparse(uri)
        query = parse_qs(parsed.query)

        if "resource" in query:
            resource_uri = query["resource"][0]
            return await self._read_resource(resource_uri)

        if "prompt" in query:
            prompt_name = query["prompt"][0]
            args = {k: v[0] for k, v in query.items() if k != "prompt"}
            return await self._get_prompt(prompt_name, args)

        raise ValueError(f"Invalid MCP URI: {uri}. Expected ?resource=<uri> or ?prompt=<name>")

    async def _read_resource(self, resource_uri: str) -> str:
        """Read a resource from the MCP server."""
        client = await self._get_client()
        contents = await client.read_resource(resource_uri)
        if contents:
            return contents[0].text or ""
        return ""

    async def _get_prompt(self, name: str, arguments: dict[str, str]) -> str:
        """Get a prompt from the MCP server."""
        client = await self._get_client()
        result = await client.get_prompt(name, arguments)
        parts = []
        for msg in result.messages:
            if hasattr(msg.content, "text"):
                parts.append(msg.content.text)
        return "\n".join(parts)

    def get_functions(self) -> dict[str, Callable[..., Awaitable[object]]]:
        return {
            "resource": self._template_resource,
            "prompt": self._template_prompt,
        }

    async def _template_resource(self, ctx: ProviderContext, uri: str) -> MCPResource:
        """Template function for MCP resources."""
        if ctx.doc_state:
            with ctx.doc_state.child(
                "mcp", detail=f"{self._instance}.resource({_strip_scheme(uri)})"
            ):
                content = await self._read_resource(uri)
        else:
            content = await self._read_resource(uri)
        return MCPResource(
            uri=build_mcp_uri(self.schemes[0], resource=uri),
            content=content,
            name=uri.split("/")[-1],
            updated=datetime.now(timezone.utc),
        )

    async def _template_prompt(
        self, ctx: ProviderContext, name: str, **arguments: str
    ) -> MCPPrompt:
        """Template function for MCP prompts."""
        if ctx.doc_state:
            with ctx.doc_state.child("mcp", detail=f"{self._instance}.prompt({name})"):
                content = await self._get_prompt(name, arguments)
        else:
            content = await self._get_prompt(name, arguments)
        return MCPPrompt(
            uri=build_mcp_uri(self.schemes[0], prompt=name, **arguments),
            content=content,
            name=name,
            updated=datetime.now(timezone.utc),
        )
