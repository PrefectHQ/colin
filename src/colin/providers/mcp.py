"""MCP Provider - Model Context Protocol integration."""

from __future__ import annotations

import asyncio
import gc
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, nullcontext
from typing import Any, ClassVar

from fastmcp import Client
from fastmcp.mcp_config import MCPConfig, RemoteMCPServer, StdioMCPServer
from pydantic import TypeAdapter, validate_call
from typing_extensions import Self

from colin.models import Ref
from colin.providers.base import Provider
from colin.providers.cache import get_compile_context
from colin.providers.resource import Resource

# TypeAdapter for parsing MCP server config from TOML
MCPServerAdapter: TypeAdapter[StdioMCPServer | RemoteMCPServer] = TypeAdapter(
    StdioMCPServer | RemoteMCPServer
)


class MCPResource(Resource):
    """Resource returned by MCPProvider.resource()."""

    def __init__(
        self,
        content: str,
        ref: Ref,
        resource_uri: str,
        name: str,
        description: str | None = None,
    ) -> None:
        """Initialize an MCP resource.

        Args:
            content: The resource content.
            ref: The Ref for this resource.
            resource_uri: The MCP resource URI that was fetched.
            name: Resource name (extracted from URI).
            description: Resource description.
        """
        super().__init__(content, ref)
        self.resource_uri = resource_uri
        self.name = name
        self.description = description


class MCPPrompt(Resource):
    """Resource returned by MCPProvider.prompt()."""

    def __init__(
        self,
        content: str,
        ref: Ref,
        name: str,
        arguments: dict[str, str],
        description: str | None = None,
    ) -> None:
        """Initialize an MCP prompt.

        Args:
            content: The prompt content.
            ref: The Ref for this resource.
            name: The prompt name.
            arguments: Arguments passed to the prompt.
            description: Prompt description.
        """
        super().__init__(content, ref)
        self.name = name
        self.arguments = arguments
        self.description = description


class MCPProvider(Provider):
    """Provider for MCP server integration.

    Template usage:
        {{ colin.mcp.github.resource("colin://issues/123") }}
        {{ colin.mcp.github.prompt("summarize", url="...") }}
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
        self._connection = name
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

        # Build client config:
        # - stdio: use transport directly with keep_alive=False workaround (fixed in fastmcp > 3.0)
        # - remote: use MCPConfig
        if isinstance(self._server, StdioMCPServer):
            transport = self._server.to_transport()
            transport.keep_alive = False  # Workaround: to_transport() bug (fixed in fastmcp > 3.0)
            client_config = transport
        else:
            client_config = MCPConfig(mcpServers={self._connection: self._server})

        async with Client(client_config) as client:
            self._client = client
            try:
                yield
            finally:
                self._client = None

        # Force cleanup while loop is still open to avoid BaseSubprocessTransport.__del__ warnings
        if isinstance(self._server, StdioMCPServer):
            del client, client_config, transport
            await asyncio.sleep(0)  # Let pending subprocess callbacks run
            gc.collect()

    def _require_client(self) -> Client:
        """Get client, raising if not initialized."""
        if self._client is None:
            raise RuntimeError("MCPProvider not initialized - use within lifespan context")
        return self._client

    async def _load_ref(self, ref: Ref) -> Resource:
        """Load resource from a Ref by dispatching on method type.

        MCP provider has special handling because 'prompt' method uses **kwargs.
        """
        if ref.method == "resource":
            return await self.resource(uri=ref.args["uri"], watch=False)
        elif ref.method == "prompt":
            name = ref.args["name"]
            arguments = ref.args.get("arguments", {})
            return await self.prompt(name=name, watch=False, **arguments)
        else:
            raise ValueError(f"Unknown MCP method: {ref.method}")

    @validate_call
    async def resource(self, uri: str, watch: bool = True) -> MCPResource:
        """Fetch MCP resource and return MCPResource.

        Args:
            uri: The MCP resource URI to fetch.
            watch: Whether to track this ref for staleness (default True).

        Returns:
            MCPResource with content and metadata.
        """
        compile_ctx = get_compile_context()
        doc_state = compile_ctx.doc_state if compile_ctx else None
        op = doc_state.child("mcp", detail=f"{self._connection}.resource") if doc_state else None

        with op if op else nullcontext():
            client = self._require_client()
            contents = await client.read_resource(uri)
            content = contents[0].text if contents else ""

            ref = Ref(
                provider=self.namespace,
                connection=self._connection,
                method="resource",
                args={"uri": uri},
            )

            resource = MCPResource(
                content=content or "",
                ref=ref,
                resource_uri=uri,
                name=uri.split("/")[-1],
            )

            if watch and compile_ctx:
                compile_ctx.track(ref, resource.version)

            return resource

    @validate_call
    async def prompt(self, name: str, watch: bool = True, **arguments: str) -> MCPPrompt:
        """Fetch MCP prompt and return MCPPrompt.

        Args:
            name: The prompt name.
            watch: Whether to track this ref for staleness (default True).
            **arguments: Arguments to pass to the prompt.

        Returns:
            MCPPrompt with content and metadata.
        """
        compile_ctx = get_compile_context()
        doc_state = compile_ctx.doc_state if compile_ctx else None
        op = (
            doc_state.child("mcp", detail=f"{self._connection}.prompt({name})")
            if doc_state
            else None
        )

        with op if op else nullcontext():
            client = self._require_client()
            result = await client.get_prompt(name, arguments)
            parts = []
            for msg in result.messages:
                if hasattr(msg.content, "text"):
                    parts.append(msg.content.text)
            content = "\n".join(parts)

            ref = Ref(
                provider=self.namespace,
                connection=self._connection,
                method="prompt",
                args={"name": name, "arguments": arguments},
            )

            prompt_resource = MCPPrompt(
                content=content,
                ref=ref,
                name=name,
                arguments=arguments,
            )

            if watch and compile_ctx:
                compile_ctx.track(ref, prompt_resource.version)

            return prompt_resource

    def get_functions(self) -> dict[str, Callable[..., Awaitable[object]]]:
        return {
            "resource": self.resource,
            "prompt": self.prompt,
        }
