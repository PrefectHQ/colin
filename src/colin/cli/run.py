"""Run, init, and clean commands."""

import asyncio
import sys
from pathlib import Path
from typing import Annotated, cast

import cyclopts
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from colin import api
from colin.compiler.state import CompilationState, OperationState, Status
from colin.exceptions import MultipleCompilationErrors, ProjectNotInitializedError

console = Console()
err_console = Console(stderr=True)


def _get_icon(op: OperationState) -> RenderableType:
    """Get display icon for an operation based on status and type."""
    if op.status == Status.FAILED:
        return Text("✗", style="red")
    if op.status == Status.SKIPPED:
        return Text("○", style="yellow")
    if op.status == Status.PROCESSING:
        return Spinner("dots", style="dim")
    if op.status == Status.PENDING:
        return Text("○", style="dim")

    # DONE - pick icon based on cached flag and operation type
    if op.cached:
        return Text("»", style="green")

    # Sources get left arrow, transforms get checkmark
    if op.name in ("ref", "mcp"):
        return Text("←", style="cyan")
    if op.name == "ctx":
        return Text("→", style="green")
    return Text("✓", style="green")


def _make_label(icon: RenderableType, text: RenderableType | str) -> RenderableType:
    """Combine icon and text into a single horizontal renderable."""
    grid = Table.grid(padding=(0, 1))
    grid.add_row(icon, text)
    return grid


def _format_uri(uri: str) -> str:
    """Format a URI for display, stripping scheme prefix."""
    if uri.startswith("project://"):
        return uri[len("project://") :]
    return f"{uri}.md"


def render_state(state: CompilationState) -> RenderableType:
    """Render compilation state for Live display.

    Shows all documents with their status and operations.

    Args:
        state: The compilation state to render.

    Returns:
        Rich renderable for display.
    """
    if not state.documents:
        return Text("")

    # Build a tree for each document, then group them
    trees: list[Tree] = []

    for uri, doc_state in state.documents.items():
        icon = _get_icon(doc_state)
        doc_tree = Tree(_make_label(icon, _format_uri(uri)), guide_style="dim")

        # Add child operations
        for child in doc_state.children:
            child_icon = _get_icon(child)

            # Build label with optional dim detail
            if child.detail:
                label = Text()
                label.append(child.name)
                label.append(f" {child.detail}", style="dim")
            else:
                label = Text(child.name)

            doc_tree.add(_make_label(child_icon, label))

        trees.append(doc_tree)

    return Group(*trees)


def print_project_info(project_file: Path, project_name: str, target_dir: Path) -> None:
    """Print project info header used by multiple commands."""
    cwd = Path.cwd()
    try:
        config_display = project_file.relative_to(cwd)
        target_display = target_dir.relative_to(cwd)
    except ValueError:
        config_display = project_file
        target_display = target_dir

    console.print(f"[dim]Config:[/]  {config_display}")
    console.print(f"[dim]Project:[/] {project_name}")
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

        if not project_file:
            raise ProjectNotInitializedError(f"No colin.toml found in {project_dir}")

        config = load_project(project_file)
        project_name = config.name
        target_dir = target or (project_file.parent / config.target_path).resolve()

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
            print_project_info(project_file, project_name, target_dir)
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
        print_project_info(project_file, project_name, target_dir)

        with Live(
            # render_state(state),
            console=console,
            refresh_per_second=10,
            auto_refresh=False,
            vertical_overflow="ellipsis",
        ) as live:
            task = asyncio.create_task(
                api.compile_project(
                    project_dir=project,
                    target_dir=target,
                    force=force,
                    dry_run=False,
                    state=state,
                )
            )
            while not task.done():
                live.update(render_state(state), refresh=True)
                await asyncio.sleep(0.1)
            # Final update before exiting Live context
            live.update(render_state(state), refresh=True)

        # Re-raise any exception from the task
        await task

    except MultipleCompilationErrors as e:
        err_console.print("\n[red bold]Compilation failed[/]\n")

        # Only show actual errors, not skipped documents
        doc_items = list(e.errors.items())
        for i, (uri, doc_errors) in enumerate(doc_items):
            is_last_doc = i == len(doc_items) - 1
            err_console.print(f"[yellow]{_format_uri(uri)}[/]")
            for j, err in enumerate(doc_errors):
                is_last_err = j == len(doc_errors) - 1
                prefix = "└──" if is_last_err else "├──"
                err_console.print(f"  {prefix} [red]✗[/] {err}")
            if not is_last_doc:
                err_console.print()
        err_console.print()

        # Summary: errors + skipped count
        error_count = sum(len(errs) for errs in e.errors.values())
        skip_msg = f", {len(e.skipped)} skipped" if e.skipped else ""
        err_console.print(
            f"[dim]{error_count} error(s) in {len(e.errors)} document(s){skip_msg}[/]"
        )
        sys.exit(1)
    except ProjectNotInitializedError as e:
        err_console.print(f"[red]Error:[/] {e}")
        err_console.print("[dim]Run `colin init` to create a new project[/]")
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
        console.print("[dim]Add .md files to models/ and run `colin run`[/]")

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
    project_file = status_info["project_file"]
    target_dir = status_info["target_dir"]

    if not project_file:
        err_console.print(f"[red]Error:[/] No colin.toml found in {project.resolve()}")
        err_console.print("[dim]Run `colin init` to create a new project[/]")
        sys.exit(1)

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
        print_project_info(project_file, status_info["project_name"], target_dir)
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
        print_project_info(project_file, status_info["project_name"], target_dir)

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
