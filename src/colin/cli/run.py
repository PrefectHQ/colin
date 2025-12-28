"""Run, init, and clean commands."""

import asyncio
import sys
from pathlib import Path
from typing import Annotated, cast

import cyclopts
from rich.console import Console
from rich.live import Live
from rich.text import Text

from colin import api
from colin.api.compile import CompileResult
from colin.exceptions import MultipleCompilationErrors, ProjectNotInitializedError
from colin.state import CompilationState, Status

console = Console()
err_console = Console(stderr=True)


def render_state(state: CompilationState) -> Text:
    """Render compilation state for Live display.

    Shows all documents with their status and operations.

    Args:
        state: The compilation state to render.

    Returns:
        Rich Text for display.
    """
    lines: list[str] = []

    for uri, doc_state in state.documents.items():
        # Status icon
        match doc_state.status:
            case Status.DONE:
                icon = "[green]✓[/]"
            case Status.PROCESSING:
                icon = "[yellow]⋯[/]"
            case Status.FAILED:
                icon = "[red]✗[/]"
            case Status.PENDING:
                icon = "[dim]○[/]"

        lines.append(f"  {icon} {uri}.md")

        # Show all child operations
        for child in doc_state.children:
            # Status icon for child
            match child.status:
                case Status.REF:
                    child_icon = "[cyan]→[/]"
                case Status.CACHED:
                    child_icon = "[cyan]⚡[/]"
                case Status.DONE:
                    child_icon = "[green]✓[/]"
                case Status.PROCESSING:
                    child_icon = "[yellow]⋯[/]"
                case Status.FAILED:
                    child_icon = "[red]✗[/]"
                case Status.PENDING:
                    child_icon = "[dim]○[/]"

            detail = f" ({child.detail})" if child.detail else ""

            # Shorten the operation name for display
            op_name = child.name
            if ":" in op_name:
                op_type, op_id = op_name.split(":", 1)
                if len(op_id) > 12:
                    op_id = op_id[:12] + "..."
                op_name = f"{op_type}:{op_id}"

            lines.append(f"      [dim]└─[/] {child_icon} {op_name}{detail}")

    return Text.from_markup("\n".join(lines)) if lines else Text("")


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


async def run(
    project: Path = Path("."),
    *,
    target: Path | None = None,
    force: bool = False,
    dry_run: bool = False,
    quiet: Annotated[bool, cyclopts.Parameter(name=["-q", "--quiet"])] = False,
) -> None:
    """Compile and run all models.

    Args:
        project: Project directory (default: current directory).
        target: Override target directory (default: from colin.toml).
        force: Force recompile all documents.
        dry_run: Show what would be run without running.
        quiet: Hide progress display, show only final results.
    """
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

        # Handle dry run
        if dry_run:
            dry_result = cast(
                list[tuple[str, Path]],
                await api.compile_project(
                    project_dir=project,
                    target_dir=target,
                    force=force,
                    dry_run=True,
                ),
            )
            print_project_info(project_name, target_dir)
            console.print(f"[bold]Would run {len(dry_result)} documents:[/]")
            for uri, _ in dry_result:
                console.print(f"  {uri}.md")
            return

        # Create state for progress tracking
        state = CompilationState()

        if quiet:
            # No output at all, just run compilation
            await api.compile_project(
                project_dir=project,
                target_dir=target,
                force=force,
                dry_run=False,
                state=state,
            )
            return

        # Print project info before starting
        print_project_info(project_name, target_dir)

        # Compile with live progress (transient=True clears display when done)
        async def compile_with_live(live: Live) -> CompileResult:
            """Run compilation while updating live display."""
            task = asyncio.create_task(
                api.compile_project(
                    project_dir=project,
                    target_dir=target,
                    force=force,
                    dry_run=False,
                    state=state,
                )
            )
            # Update display while waiting
            while not task.done():
                live.update(render_state(state))
                await asyncio.sleep(0.1)
            # Cast is safe because dry_run=False means CompileResult is returned
            return cast(CompileResult, await task)

        with Live(Text(""), console=console, refresh_per_second=10) as live:
            await compile_with_live(live)
            # Final update to show completed state
            live.update(render_state(state))

    except MultipleCompilationErrors as e:
        err_console.print("\n[red bold]Compilation failed[/]")
        err_console.print()
        doc_items = list(e.errors.items())
        for i, (uri, doc_errors) in enumerate(doc_items):
            is_last_doc = i == len(doc_items) - 1
            err_console.print(f"[yellow]{uri}.md[/]")
            for j, err in enumerate(doc_errors):
                is_last_err = j == len(doc_errors) - 1
                prefix = "└──" if is_last_err else "├──"
                err_console.print(f"  {prefix} [red]✗[/] {err}")
            if not is_last_doc:
                err_console.print()
        err_console.print()
        error_count = sum(len(errs) for errs in e.errors.values())
        err_console.print(f"[dim]{error_count} error(s) in {len(e.errors)} document(s)[/]")
        sys.exit(1)
    except ProjectNotInitializedError as e:
        err_console.print(f"[red]Error:[/] {e}")
        err_console.print("[dim]Run `cbt init` to create a new project[/]")
        sys.exit(1)
    except ValueError as e:
        err_console.print(f"[red]Error:[/] {e}")
        sys.exit(1)
    except Exception as e:
        err_console.print(f"[red]Unexpected error:[/] {e}")
        sys.exit(1)


def init(
    project: Path = Path("."),
    *,
    name: str | None = None,
    models: str = "models",
    target: str = "target",
) -> None:
    """Initialize a new Colin project.

    Creates colin.toml and models directory.

    Args:
        project: Project directory (default: current directory).
        name: Project name (default: directory name).
        models: Path to models directory (default: "models").
        target: Path to target directory (default: "target").
    """
    project_dir = project.resolve()

    try:
        project_file, model_dir = api.init_project(
            directory=project_dir,
            name=name,
            model_path=models,
            target_path=target,
        )

        cwd = Path.cwd()
        try:
            project_display = project_file.relative_to(cwd)
            model_display = model_dir.relative_to(cwd)
        except ValueError:
            project_display = project_file
            model_display = model_dir

        console.print(f"[green]Created:[/] {project_display}")
        console.print(f"[green]Created:[/] {model_display}/")
        console.print()
        console.print("[dim]Add .md files to models/ and run `cbt run`[/]")

    except FileExistsError as e:
        err_console.print(f"[red]Error:[/] {e}")
        sys.exit(1)


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
