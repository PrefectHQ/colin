"""Colin CLI - thin shell over API functions."""

import cyclopts
from rich.console import Console

from colin.cli import mcp, run

console = Console()
err_console = Console(stderr=True)

app = cyclopts.App(name="cbt", help="Colin - Context compiler for the AI era.")

# Register subcommands
app.command(run.run)
app.command(run.init)
app.command(run.clean)

# Register mcp subcommand group
app.command(mcp.app, name="mcp")


def main() -> None:
    """Entry point for the CLI."""
    app()
