"""MCP Provider - Model Context Protocol integration."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, ClassVar, Literal

from fastmcp import Client
from fastmcp.mcp_config import MCPConfig, RemoteMCPServer, StdioMCPServer
from pydantic import TypeAdapter
from typing_extensions import Self

from colin.models import Address
from colin.providers.addressable import Addressable
from colin.providers.base import Provider
from colin.providers.cache import get_compile_context

# TypeAdapter for parsing MCP server config from TOML
MCPServerAdapter: TypeAdapter[StdioMCPServer | RemoteMCPServer] = TypeAdapter(
    StdioMCPServer | RemoteMCPServer
)


@dataclass
class MCPResource(Addressable):
    """Domain object returned by colin.mcp.<name>.resource(). Inherits from Addressable."""

    resource_uri: str
    """The MCP resource URI that was fetched."""

    _content: str
    """The resource content."""

    name: str
    """Resource name (extracted from URI)."""

    description: str | None = None
    """Resource description."""

    _last_updated: datetime | None = None
    """When this resource was last modified."""

    _instance: str = field(default="", repr=False)
    """Provider instance name."""

    @property
    def content(self) -> str:
        return self._content

    @property
    def last_updated(self) -> datetime:
        return self._last_updated or datetime.now(timezone.utc)

    def address(self) -> Address:
        return Address(
            provider="mcp",
            instance=self._instance,
            payload={"type": "resource", "uri": self.resource_uri},
        )


@dataclass
class MCPPrompt(Addressable):
    """Domain object returned by colin.mcp.<name>.prompt(). Inherits from Addressable."""

    name: str
    """The prompt name."""

    arguments: dict[str, str]
    """Arguments passed to the prompt."""

    _content: str
    """The prompt content."""

    description: str | None = None
    """Prompt description."""

    _last_updated: datetime | None = None
    """When this prompt was last retrieved."""

    _instance: str = field(default="", repr=False)
    """Provider instance name."""

    @property
    def content(self) -> str:
        return self._content

    @property
    def last_updated(self) -> datetime:
        return self._last_updated or datetime.now(timezone.utc)

    def address(self) -> Address:
        return Address(
            provider="mcp",
            instance=self._instance,
            payload={"type": "prompt", "name": self.name, "arguments": self.arguments},
        )


class MCPProvider(Provider):
    """Provider for MCP server integration.

    Template usage:
        {{ colin.mcp.github.resource("colin://issues/123") }}
        {{ colin.mcp.github.prompt("summarize", url="...") }}

    Payload format for load_address:
    - Resource: {"type": "resource", "uri": "colin://hello"}
    - Prompt: {"type": "prompt", "name": "greet", "arguments": {"name": "Alice"}}
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

    async def load_address(self, payload: dict[str, Any]) -> MCPResource | MCPPrompt:
        """Load content from address payload.

        Args:
            payload: Dict with 'type' and type-specific fields.
                - Resource: {"type": "resource", "uri": "colin://hello"}
                - Prompt: {"type": "prompt", "name": "greet", "arguments": {...}}

        Returns:
            MCPResource or MCPPrompt.

        Raises:
            ValueError: If payload type is invalid.
        """
        payload_type: Literal["resource", "prompt"] = payload["type"]

        if payload_type == "resource":
            resource_uri = payload["uri"]
            return await self._fetch_resource(resource_uri)

        if payload_type == "prompt":
            prompt_name = payload["name"]
            arguments = payload.get("arguments", {})
            return await self._fetch_prompt(prompt_name, arguments)

        raise ValueError(f"Invalid MCP payload type: {payload_type}")

    async def _fetch_resource(self, resource_uri: str) -> MCPResource:
        """Fetch MCP resource."""
        client = self._require_client()
        contents = await client.read_resource(resource_uri)
        content = contents[0].text if contents else ""

        return MCPResource(
            resource_uri=resource_uri,
            _content=content or "",
            name=resource_uri.split("/")[-1],
            _last_updated=datetime.now(timezone.utc),
            _instance=self._instance,
        )

    async def _fetch_prompt(self, name: str, arguments: dict[str, str]) -> MCPPrompt:
        """Fetch MCP prompt."""
        client = self._require_client()
        result = await client.get_prompt(name, arguments)
        parts = []
        for msg in result.messages:
            if hasattr(msg.content, "text"):
                parts.append(msg.content.text)
        content = "\n".join(parts)

        return MCPPrompt(
            name=name,
            arguments=arguments,
            _content=content,
            _last_updated=datetime.now(timezone.utc),
            _instance=self._instance,
        )

    def get_functions(self) -> dict[str, Callable[..., Awaitable[object]]]:
        return {
            "resource": self.resource,
            "prompt": self.prompt,
        }

    async def resource(self, uri: str) -> MCPResource:
        """Fetch MCP resource and return MCPResource."""
        compile_ctx = get_compile_context()
        doc_state = compile_ctx.doc_state if compile_ctx else None
        op = doc_state.child("mcp", detail=f"{self._instance}.resource") if doc_state else None
        with op if op else nullcontext():
            return await self._fetch_resource(uri)

    async def prompt(self, name: str, **arguments: str) -> MCPPrompt:
        """Fetch MCP prompt and return MCPPrompt."""
        compile_ctx = get_compile_context()
        doc_state = compile_ctx.doc_state if compile_ctx else None
        op = (
            doc_state.child("mcp", detail=f"{self._instance}.prompt({name})") if doc_state else None
        )
        with op if op else nullcontext():
            return await self._fetch_prompt(name, arguments)
