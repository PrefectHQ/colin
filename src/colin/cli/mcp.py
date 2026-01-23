"""MCP server management commands."""

import asyncio
import sys
from pathlib import Path
from typing import Annotated, Literal

import cyclopts
from cyclopts import Parameter
from fastmcp import Client
from fastmcp.mcp_config import MCPConfig, RemoteMCPServer, StdioMCPServer
from rich import box
from rich.console import Console
from rich.table import Table

from colin.api import mcp
from colin.providers.oauth_store import OAUTH_STORAGE_DIR

console = Console()
err_console = Console(stderr=True)

app = cyclopts.App(name="mcp", help="Manage MCP servers.")

# Auth subcommand group
auth_app = cyclopts.App(name="auth", help="Manage OAuth authentication for MCP providers.")
app.command(auth_app)


@auth_app.command
def clear(
    *,
    force: Annotated[
        bool,
        Parameter(name=["-f", "--force"]),
    ] = False,
) -> None:
    """Clear stored OAuth tokens.

    This removes cached authentication tokens for all MCP providers (Linear,
    Notion, etc.), requiring re-authentication on next use.

    Useful when experiencing authentication errors (e.g., 500s).

    Examples:
      colin mcp auth clear
      colin mcp auth clear -f  # skip confirmation

    Args:
        force: Skip confirmation prompt.
    """
    if not OAUTH_STORAGE_DIR.exists():
        console.print("[dim]No OAuth tokens stored.[/]")
        return

    files = list(OAUTH_STORAGE_DIR.iterdir())
    if not files:
        console.print("[dim]No OAuth tokens stored.[/]")
        return

    # Confirm unless --force
    if not force:
        if not sys.stdin.isatty():
            err_console.print("[red]Error:[/] Confirmation required. Use -f to confirm.")
            sys.exit(1)

        console.print("[bold]Clear all MCP OAuth tokens?[/]")
        console.print("[dim]This will require re-authentication for Linear, Notion, etc.[/]")
        console.print()
        confirm = console.input("[bold]Continue?[/] [dim](y/N)[/] ")
        if confirm.lower() not in ("y", "yes"):
            console.print("[dim]Cancelled.[/]")
            return

    # Delete all files in the directory
    deleted = 0
    for f in files:
        try:
            if f.is_file():
                f.unlink()
                deleted += 1
        except OSError as e:
            err_console.print(f"[red]Error:[/] {e}")

    if deleted > 0:
        console.print("[green]Cleared OAuth tokens.[/]")
        console.print("[dim]Re-authentication will be required on next use.[/]")
    else:
        console.print("[dim]No tokens deleted.[/]")


@app.command
def add(
    name: str,
    command_or_url: str,
    args: Annotated[list[str] | None, Parameter(negative=())] = None,
    *,
    transport: Annotated[
        Literal["stdio", "sse", "http"] | None,
        Parameter(name=["-t", "--transport"]),
    ] = None,
    env: Annotated[
        list[str] | None,
        Parameter(name=["-e", "--env"]),
    ] = None,
    project: Path = Path("."),
) -> None:
    """Add an MCP server.

    Examples:
      # Add HTTP server:
      colin mcp add sentry https://mcp.sentry.dev/mcp --transport http

      # Add stdio server:
      colin mcp add airtable npx -y airtable-mcp-server -e AIRTABLE_API_KEY=xxx

      # Add stdio server (default transport):
      colin mcp add greeter uvx fastmcp run server.py

    Args:
        name: Server name (used in templates as mcp.<name>.resource(...)).
        command_or_url: Command to run (stdio) or URL (http/sse).
        args: Additional arguments for stdio command.
        transport: Transport type: stdio, sse, or http. Defaults to stdio.
        env: Environment variables in KEY=VALUE format (stdio only).
        project: Project directory.
    """
    # Determine transport type
    if transport is None:
        if command_or_url.startswith(("http://", "https://")):
            if command_or_url.endswith("/sse"):
                transport = "sse"
            else:
                transport = "http"
        else:
            transport = "stdio"

    if transport not in ("stdio", "sse", "http"):
        err_console.print(f"[red]Error:[/] Invalid transport: {transport}")
        err_console.print("[dim]Valid options: stdio, sse, http[/]")
        sys.exit(1)

    is_remote = transport in ("http", "sse")

    if is_remote and (args or env):
        err_console.print("[red]Error:[/] --env and args only apply to stdio transport")
        sys.exit(1)

    # Parse env list into dict
    env_dict: dict[str, str] = {}
    for item in env or []:
        if "=" not in item:
            err_console.print(f"[red]Error:[/] Invalid env format: {item} (expected KEY=VALUE)")
            sys.exit(1)
        key, value = item.split("=", 1)
        env_dict[key] = value

    # Build server config
    if is_remote:
        server: StdioMCPServer | RemoteMCPServer = RemoteMCPServer(url=command_or_url)
    else:
        server = StdioMCPServer(
            command=command_or_url,
            args=args or [],
            env=env_dict,
        )

    try:
        mcp.add_server(project_dir=project, name=name, server=server)
        console.print(f"[green]Added MCP server:[/] {name}")
    except FileNotFoundError as e:
        err_console.print(f"[red]Error:[/] {e}")
        err_console.print("[dim]Run `colin init` to create a new project[/]")
        sys.exit(1)
    except ValueError as e:
        err_console.print(f"[red]Error:[/] {e}")
        sys.exit(1)


@app.command
def remove(
    name: str,
    *,
    project: Path = Path("."),
) -> None:
    """Remove an MCP server.

    Args:
        name: Server name to remove.
        project: Project directory.
    """
    try:
        mcp.remove_server(project_dir=project, name=name)
        console.print(f"[green]Removed:[/] {name}")
    except FileNotFoundError as e:
        err_console.print(f"[red]Error:[/] {e}")
        err_console.print("[dim]Run `colin init` to create a new project[/]")
        sys.exit(1)
    except ValueError as e:
        err_console.print(f"[red]Error:[/] {e}")
        sys.exit(1)


@app.command(name="list")
def list_servers(
    *,
    project: Path = Path("."),
) -> None:
    """List configured MCP servers.

    Args:
        project: Project directory.
    """
    try:
        servers = mcp.list_servers(project_dir=project)

        if not servers:
            console.print("[dim]No MCP servers configured.[/]")
            return

        table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
        table.add_column("Name", style="cyan")
        table.add_column("Type", style="dim")
        table.add_column("Connection")

        for name, server in servers.items():
            if isinstance(server, RemoteMCPServer):
                server_type = "http"
                connection = server.url
            else:
                server_type = "stdio"
                cmd_parts = [server.command] + server.args
                connection = " ".join(cmd_parts)

            table.add_row(name, server_type, connection)

        console.print(table)
    except FileNotFoundError as e:
        err_console.print(f"[red]Error:[/] {e}")
        err_console.print("[dim]Run `colin init` to create a new project[/]")
        sys.exit(1)


@app.command
def test(
    name: str,
    *,
    project: Path = Path("."),
) -> None:
    """Test connection to an MCP server.

    Connects to the server and lists available resources.

    Args:
        name: Server name to test.
        project: Project directory.
    """
    try:
        servers = mcp.list_servers(project_dir=project)
    except FileNotFoundError as e:
        err_console.print(f"[red]Error:[/] {e}")
        err_console.print("[dim]Run `colin init` to create a new project[/]")
        sys.exit(1)

    if name not in servers:
        err_console.print(f"[red]Error:[/] MCP server '{name}' not found")
        err_console.print("[dim]Use `colin mcp list` to see configured servers[/]")
        sys.exit(1)

    server = servers[name]
    console.print(f"[dim]Testing connection to[/] {name}...")

    async def do_test() -> None:
        single_config = MCPConfig(mcpServers={name: server})
        client = Client(single_config)

        try:
            async with client:
                tools = await client.list_tools()
                resources = await client.list_resources()
                prompts = await client.list_prompts()

                console.print(f"[green]✓[/] Connected to {name}")
                console.print(
                    f"  [cyan]{len(tools)}[/] tools, "
                    f"[cyan]{len(resources)}[/] resources, "
                    f"[cyan]{len(prompts)}[/] prompts"
                )

        except Exception as e:
            err_console.print(f"[red]✗[/] Failed to connect: {e}")
            sys.exit(1)

    asyncio.run(do_test())
