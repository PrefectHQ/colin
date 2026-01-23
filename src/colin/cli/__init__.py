"""Colin CLI - thin shell over API functions."""

import cyclopts
from rich.console import Console

from colin.cli import mcp, run, skills

console = Console()
err_console = Console(stderr=True)

app = cyclopts.App(
    name="colin",
    help="Colin - Context compiler for the AI era.",
    default_parameter=cyclopts.Parameter(negative=()),
)

# Register subcommands
app.command(run.run)
app.command(run.update)
app.command(run.init)
app.command(run.clean)
app.command(run.status)

# Register subcommand groups
app.command(mcp.app, name="mcp")
app.command(skills.app, name="skills")


def main() -> None:
    """Entry point for the CLI."""
    app()
