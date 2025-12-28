"""MCP server management commands."""

import sys
from pathlib import Path

import cyclopts
from fastmcp.mcp_config import RemoteMCPServer
from rich.console import Console
from rich.table import Table

from colin import api

console = Console()
err_console = Console(stderr=True)

app = cyclopts.App(name="mcp", help="Manage MCP servers.")


@app.command
def add(
    name: str,
    *,
    url: str | None = None,
    command: str | None = None,
    args: list[str] | None = None,
    project: Path = Path("."),
) -> None:
    """Add an MCP server.

    Args:
        name: Server name (used in templates as mcp_resource('name', ...)).
        url: Server URL for HTTP/SSE transport.
        command: Command to run for stdio transport.
        args: Arguments for stdio command.
        project: Project directory (default: current directory).
    """
    if not url and not command:
        err_console.print("[red]Error:[/] Either --url or --command is required")
        sys.exit(1)

    if url and command:
        err_console.print("[red]Error:[/] Cannot specify both --url and --command")
        sys.exit(1)

    try:
        api.mcp.add_server(
            project_dir=project,
            name=name,
            url=url,
            command=command,
            args=args or [],
        )
        console.print(f"[green]Added:[/] {name}")
    except FileNotFoundError as e:
        err_console.print(f"[red]Error:[/] {e}")
        err_console.print("[dim]Run `cbt init` to create a new project[/]")
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
        project: Project directory (default: current directory).
    """
    try:
        api.mcp.remove_server(project_dir=project, name=name)
        console.print(f"[green]Removed:[/] {name}")
    except FileNotFoundError as e:
        err_console.print(f"[red]Error:[/] {e}")
        err_console.print("[dim]Run `cbt init` to create a new project[/]")
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
        project: Project directory (default: current directory).
    """
    try:
        mcp_config = api.mcp.list_servers(project_dir=project)

        if not mcp_config.mcpServers:
            console.print("[dim]No MCP servers configured.[/]")
            return

        table = Table(show_header=True, header_style="bold")
        table.add_column("Name")
        table.add_column("Type")
        table.add_column("Connection")

        for name, server in mcp_config.mcpServers.items():
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
        err_console.print("[dim]Run `cbt init` to create a new project[/]")
        sys.exit(1)
