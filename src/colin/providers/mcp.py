"""MCP Provider - Model Context Protocol integration."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, nullcontext
from typing import Any, ClassVar

from fastmcp import Client
from fastmcp.mcp_config import MCPConfig, RemoteMCPServer, StdioMCPServer
from mcp.types import Tool
from pydantic import TypeAdapter, validate_call
from typing_extensions import Self

from colin.compiler.cache import get_compile_context
from colin.models import Ref
from colin.providers.base import Provider
from colin.providers.mcp_types import MCPServerConfig, MCPServerInfo
from colin.resources import Resource

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
        # Set keep_alive=False for stdio servers to ensure proper subprocess cleanup
        # and avoid "Event loop is closed" warnings during shutdown.
        if "command" in config and "keep_alive" not in config:
            config = {**config, "keep_alive": False}
        server = MCPServerAdapter.validate_python(config)
        return cls(name, server)

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        """Manage MCP client lifecycle."""
        if self._server is None:
            raise RuntimeError("MCPProvider not configured - use from_config()")
        mcp_config = MCPConfig(mcpServers={self._connection: self._server})
        try:
            async with Client(mcp_config) as client:
                self._client = client
                yield
        except Exception as e:
            # Provide helpful context for connection failures
            server_info = self._format_server_info()
            raise RuntimeError(
                f"Failed to connect to MCP server '{self._connection}'\n"
                f"  {server_info}\n"
                f"  Error: {e}"
            ) from None
        finally:
            self._client = None

    def _format_server_info(self) -> str:
        """Format server connection info for error messages."""
        if isinstance(self._server, StdioMCPServer):
            cmd = self._server.command
            args = " ".join(self._server.args) if self._server.args else ""
            return f"Command: {cmd} {args}".strip()
        else:
            # RemoteMCPServer
            return f"URL: {self._server.url}"

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

    async def get_ref_version(self, ref: Ref) -> str:
        """Get current version for a ref.

        For list_tools and server_info, we compute versions directly
        without returning full Resource objects.
        """
        if ref.method == "list_tools":
            tools = await self.list_tools(watch=False)
            return str(len(tools))
        elif ref.method == "server_info":
            info = await self.server_info(watch=False)
            return info.version
        else:
            # For resource and prompt, use the default behavior
            resource = await self._load_ref(ref)
            return resource.version

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

    async def list_tools(self, watch: bool = True) -> list[Tool]:
        """List available tools from the MCP server.

        Returns MCP SDK Tool objects with:
        - name: str (programmatic identifier)
        - title: str | None (human-readable name)
        - description: str | None
        - inputSchema: dict (JSON Schema for parameters)
        - outputSchema: dict | None (JSON Schema for return value)

        Args:
            watch: Whether to track this ref for staleness (default True).

        Returns:
            List of Tool objects from the MCP server.
        """
        compile_ctx = get_compile_context()
        doc_state = compile_ctx.doc_state if compile_ctx else None
        op = doc_state.child("mcp", detail=f"{self._connection}.list_tools") if doc_state else None

        with op if op else nullcontext():
            client = self._require_client()
            tools = await client.list_tools()

            if watch and compile_ctx:
                # Track as a ref so staleness detection works
                ref = Ref(
                    provider=self.namespace,
                    connection=self._connection,
                    method="list_tools",
                    args={},
                )
                # Use tool count as a simple version indicator
                version = str(len(tools))
                compile_ctx.track(ref, version)

            return tools

    async def server_info(self, watch: bool = True) -> MCPServerInfo:
        """Get server metadata (name, description, version, etc.).

        Args:
            watch: Whether to track this ref for staleness (default True).

        Returns:
            MCPServerInfo with server metadata.
        """
        compile_ctx = get_compile_context()
        doc_state = compile_ctx.doc_state if compile_ctx else None
        op = doc_state.child("mcp", detail=f"{self._connection}.server_info") if doc_state else None

        with op if op else nullcontext():
            client = self._require_client()
            init_result = client.initialize_result
            if init_result is None:
                raise RuntimeError("MCP client not initialized")

            server_info = MCPServerInfo(
                name=init_result.serverInfo.name,
                version=init_result.serverInfo.version,
                title=init_result.serverInfo.title,
                instructions=init_result.instructions,
                website_url=init_result.serverInfo.websiteUrl,
            )

            if watch and compile_ctx:
                ref = Ref(
                    provider=self.namespace,
                    connection=self._connection,
                    method="server_info",
                    args={},
                )
                # Use server version as the version indicator
                compile_ctx.track(ref, server_info.version)

            return server_info

    async def config(self) -> MCPServerConfig:
        """Get server configuration (command, args, env, or URL for remote servers).

        Returns:
            MCPServerConfig with connection details.
        """
        if isinstance(self._server, StdioMCPServer):
            return MCPServerConfig(
                command=self._server.command,
                args=list(self._server.args) if self._server.args else [],
                env=dict(self._server.env) if self._server.env else {},
            )
        else:
            # RemoteMCPServer
            return MCPServerConfig(
                url=self._server.url,
                headers=dict(self._server.headers) if self._server.headers else {},
            )

    def get_functions(self) -> dict[str, Callable[..., Awaitable[object]]]:
        return {
            "resource": self.resource,
            "prompt": self.prompt,
            "list_tools": self.list_tools,
            "server_info": self.server_info,
            "config": self.config,
        }
