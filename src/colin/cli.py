"""Colin CLI using cyclopts - thin shell over API functions."""

import asyncio
import sys
from pathlib import Path
from typing import Annotated

import cyclopts
from rich.console import Console
from rich.table import Table

from colin import api

console = Console()
err_console = Console(stderr=True)

app = cyclopts.App(name="cbt", help="Colin - Context compiler for the AI era.")


def print_project_info(project_name: str | None, target_dir: Path) -> None:
    """Print project info header used by multiple commands."""
    cwd = Path.cwd()
    try:
        target_display = target_dir.relative_to(cwd)
    except ValueError:
        target_display = target_dir

    console.print(f"[dim]Project:[/] {project_name or 'N/A'}")
    console.print(f"[dim]Target:[/]  {target_display}/")
    console.print()


@app.command
def run(
    project: Path = Path("."),
    *,
    target: Path | None = None,
    force: bool = False,
    dry_run: bool = False,
    init: bool = False,
) -> None:
    """Compile and run all models.

    Args:
        project: Project directory (default: current directory).
        target: Override target directory (default: from colin.toml or ./target/).
        force: Force recompile all documents.
        dry_run: Show what would be run without running.
        init: Create a new colin.toml if none exists.
    """
    asyncio.run(_run_async(
        project=project,
        target=target,
        force=force,
        dry_run=dry_run,
        init=init,
    ))


async def _run_async(
    *,
    project: Path,
    target: Path | None,
    force: bool,
    dry_run: bool,
    init: bool,
) -> None:
    """Async implementation of run command."""
    try:
        # Get project info for display
        from colin.api.project import find_project_file, load_project

        project_dir = project.resolve()
        project_file = find_project_file(project_dir)

        if project_file:
            config = load_project(project_file)
            project_name = config.name
            target_dir = target or (project_file.parent / config.target_path).resolve()
        else:
            project_name = None
            target_dir = target or Path("target").resolve()

        # Compile or dry run
        result = await api.compile_project(
            project_dir=project,
            target_dir=target,
            force=force,
            init_if_missing=init,
            dry_run=dry_run,
        )

        if dry_run:
            # result is list of (uri, path) tuples
            print_project_info(project_name, target_dir)
            console.print(f"[bold]Would run {len(result)} documents:[/]")
            for uri, _ in result:
                console.print(f"  {uri}.md")
            return

        # result is CompileResult
        print_project_info(result.project_name, target_dir)

        with console.status("[dim]Running...", spinner="dots"):
            # Compilation already happened, just show results
            pass

        for doc in result.compiled:
            llm_info = f" [dim]({len(doc.llm_calls)} LLM)[/]" if doc.llm_calls else ""
            console.print(f"  [green]✓[/] {doc.uri}.md{llm_info}")

        # Summary line
        summary_parts = [f"[bold]{len(result.compiled)}[/] documents"]
        if result.total_llm_calls > 0:
            summary_parts.append(f"{result.total_llm_calls} LLM calls")
            if result.total_cost > 0:
                summary_parts[-1] += f" (${result.total_cost:.4f})"
        console.print(f"\n[green]Done.[/] {' · '.join(summary_parts)}")

    except ValueError as e:
        err_console.print(f"[red]Error:[/] {e}")
        sys.exit(1)
    except Exception as e:
        err_console.print(f"[red]Unexpected error:[/] {e}")
        sys.exit(1)


@app.command
def status(
    project: Path = Path("."),
) -> None:
    """Show run status.

    Args:
        project: Project directory (default: current directory).
    """
    status_info = api.get_project_status(project)

    if not status_info["manifest_exists"] or status_info["document_count"] == 0:
        console.print("[dim]No documents run yet.[/]")
        return

    print_project_info(status_info["project_name"], status_info["target_dir"])

    table = Table(show_header=True, header_style="bold")
    table.add_column("Document")
    table.add_column("LLM Calls", justify="right")
    table.add_column("Cost", justify="right")

    for uri, info in sorted(status_info["documents"].items()):
        llm_calls = str(info["llm_calls"]) if info["llm_calls"] > 0 else "-"
        cost = f"${info['cost']:.4f}" if info["cost"] > 0 else "-"
        table.add_row(uri, llm_calls, cost)

    console.print(table)

    if status_info["compiled_at"]:
        console.print(f"\n[dim]Last run: {status_info['compiled_at']:%Y-%m-%d %H:%M}[/]")


@app.command
def clean(
    project: Path = Path("."),
    *,
    yes: Annotated[bool, cyclopts.Parameter(name=["-y", "--yes"])] = False,
) -> None:
    """Remove target directory (compiled outputs and manifest).

    Args:
        project: Project directory (default: current directory).
        yes: Skip confirmation prompt.
    """
    status_info = api.get_project_status(project)
    target_dir = status_info["target_dir"]

    if not target_dir.exists():
        console.print("[dim]Nothing to clean.[/]")
        return

    # Collect files for display
    files_in_target: list[str] = []
    project_dir = project.resolve()
    for path in target_dir.rglob("*"):
        if path.is_file():
            try:
                rel = path.relative_to(project_dir)
                files_in_target.append(str(rel))
            except ValueError:
                files_in_target.append(str(path))

    # Show what will be removed
    if not yes:
        print_project_info(status_info["project_name"], target_dir)
        console.print("[bold]Will remove:[/]")
        for rel in files_in_target:
            console.print(f"  [yellow]{rel}[/]")
        console.print()
        confirm = console.input("[bold]Continue?[/] [dim](y/N)[/] ")
        if confirm.lower() not in ("y", "yes"):
            console.print("[dim]Cancelled.[/]")
            return

    # Show project info if skipping confirmation
    if yes:
        print_project_info(status_info["project_name"], target_dir)

    # Remove files
    removed = api.clean_project(project)

    # Show what was removed
    console.print("[bold]Removed:[/]")
    for path in removed:
        try:
            rel = path.relative_to(project_dir)
            console.print(f"  [dim]{rel}[/]")
        except ValueError:
            console.print(f"  [dim]{path}[/]")


def main() -> None:
    """Entry point for the CLI."""
    app()
