"""MCP Provider - Model Context Protocol integration.

Provides a read-only provider for mcp:// and mcp.{instance}:// URIs.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import parse_qs, urlencode, urlparse

from fastmcp import Client
from fastmcp.mcp_config import MCPConfig, RemoteMCPServer, StdioMCPServer
from pydantic import TypeAdapter
from typing_extensions import Self

from colin.providers.base import Provider
from colin.providers.context import ProviderContext

if TYPE_CHECKING:
    from colin.models import RefResult

# TypeAdapter for parsing MCP server config from TOML
MCPServerAdapter: TypeAdapter[StdioMCPServer | RemoteMCPServer] = TypeAdapter(
    StdioMCPServer | RemoteMCPServer
)


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


class MCPProvider(Provider):
    """Read-only provider for MCP server integration.

    Each MCP server instance becomes a provider with scheme mcp.{name}.

    URI format: mcp://?resource=<url-encoded-uri> (default instance)
    or: mcp.{instance}://?resource=<url-encoded-uri>
    or: mcp.{instance}://?prompt=<name>&arg1=val1&arg2=val2
    """

    namespace: ClassVar[str] = "mcp"

    def __init__(self, name: str, server: StdioMCPServer | RemoteMCPServer) -> None:
        """Initialize MCPProvider with server instance.

        Args:
            name: Instance name (required).
            server: StdioMCPServer or RemoteMCPServer instance.
        """
        if not name:
            raise ValueError("MCP provider requires an instance name")

        super().__init__()
        self._instance = name
        self._server = server
        self._client = None
        self.schemes = [f"mcp.{name}"]

    @classmethod
    def from_config(cls, name: str | None, config: dict[str, Any]) -> Self:
        """Create MCP provider from TOML configuration.

        Args:
            name: Instance name from TOML config.
            config: Config dict with command, args, env, url, headers.

        Returns:
            Configured MCPProvider instance.
        """
        if not name:
            raise ValueError("MCP provider requires an instance name")
        server = MCPServerAdapter.validate_python(config)
        return cls(name, server)

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        """Manage MCP client lifecycle."""
        if self._server is None:
            raise RuntimeError("MCPProvider not configured - use from_config()")
        mcp_config = MCPConfig(mcpServers={self._instance: self._server})
        async with Client(mcp_config) as client:
            self._client = client
            yield
        self._client = None

    def _require_client(self) -> Client:
        """Get client, raising if not initialized."""
        if self._client is None:
            raise RuntimeError("MCPProvider not initialized - use within lifespan context")
        return self._client

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
        client = self._require_client()
        contents = await client.read_resource(resource_uri)
        if contents:
            return contents[0].text or ""
        return ""

    async def _get_prompt(self, name: str, arguments: dict[str, str]) -> str:
        """Get a prompt from the MCP server."""
        client = self._require_client()
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
