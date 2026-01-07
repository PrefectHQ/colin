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

from colin.api.compile import CompileResult, compile_project
from colin.api.project import (
    clean_project,
    find_project_file,
    get_stale_files,
    load_project,
)
from colin.compiler.state import CompilationState, OperationState, Status
from colin.exceptions import MultipleCompilationErrors, ProjectNotInitializedError

console = Console()
err_console = Console(stderr=True)


def _plural(n: int, singular: str, plural: str) -> str:
    """Return singular or plural form based on count."""
    return singular if n == 1 else plural


def _get_icon(op: OperationState) -> RenderableType:
    """Get display icon for an operation based on status and type."""
    if op.status == Status.FAILED:
        return Text("✗", style="red")
    if op.status == Status.SKIPPED:
        # SKIPPED is only for upstream failures now (cached files use DONE)
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
    """Format a URI for display, showing path from models/."""
    if uri.startswith("project://"):
        path = uri[len("project://") :]
        # Show as models/path for clarity
        return f"models/{path}"
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


def print_project_info(project_file: Path, project_name: str, output_dir: Path) -> None:
    """Print project info header used by multiple commands."""
    cwd = Path.cwd()
    try:
        config_display = project_file.relative_to(cwd)
        output_display = output_dir.relative_to(cwd)
    except ValueError:
        config_display = project_file
        output_display = output_dir

    console.print(f"[dim]Project:[/]    {project_name}")
    console.print(f"[dim]Config:[/]     {config_display}")
    console.print(f"[dim]Output dir:[/] {output_display}/")
    console.print()


async def _compile_with_progress(
    project_dir: Path,
    output_dir: Path | None = None,
    force: bool = False,
    ephemeral: bool = False,
    vars: dict[str, str] | None = None,
    state: CompilationState | None = None,
) -> CompileResult:
    """Compile project with live progress display.

    Args:
        project_dir: Project directory to compile.
        output_dir: Override output directory.
        force: Force recompile.
        ephemeral: Don't write to .colin/.
        vars: Variable overrides.
        state: Compilation state for tracking (created if None).

    Returns:
        CompileResult with compiled documents and manifest.
    """
    if state is None:
        state = CompilationState()

    console.print("[dim]Processing:[/]")
    with Live(
        console=console,
        refresh_per_second=10,
        auto_refresh=False,
        vertical_overflow="ellipsis",
    ) as live:
        task = asyncio.create_task(
            compile_project(
                project_dir=project_dir,
                output_dir=output_dir,
                force=force,
                ephemeral=ephemeral,
                vars=vars,
                state=state,
            )
        )
        while not task.done():
            live.update(render_state(state), refresh=True)
            await asyncio.sleep(0.1)
        # Final update
        live.update(render_state(state), refresh=True)
        result = await task

    # Show output files
    assert isinstance(result, CompileResult)
    output_files = []
    for doc in result.compiled:
        if doc.frontmatter.colin.output.should_publish(doc.uri) and doc.output_path:
            output_files.append(doc.output_path)

    if output_files:
        console.print()
        console.print("[dim]Output:[/]")
        for path in sorted(output_files):
            console.print(f"[green]→[/green] {path}")

    return result


async def run(
    project: Path = Path("."),
    *,
    output: Annotated[Path | None, cyclopts.Parameter(name=["-o", "--output"])] = None,
    no_cache: Annotated[bool, cyclopts.Parameter(name=["--no-cache"])] = False,
    ephemeral: Annotated[bool, cyclopts.Parameter(name=["--ephemeral"])] = False,
    dry_run: bool = False,
    quiet: Annotated[bool, cyclopts.Parameter(name=["-q", "--quiet"])] = False,
    var: Annotated[list[str], cyclopts.Parameter(name=["--var"])] = [],
) -> None:
    """Compile and run all models.

    Args:
        project: Project directory (default: current directory).
        output: Override output directory (default: from colin.toml).
        no_cache: Ignore cached results and recompile all documents.
        ephemeral: Don't write to .colin/ directory (for testing, CI, one-off runs).
        dry_run: Show what would be run without running.
        quiet: Hide progress display, show only final results.
        var: Variable overrides in key=value format (can be repeated).
    """
    # Parse --var key=value pairs into dict
    vars_dict: dict[str, str] | None = None
    if var:
        vars_dict = {}
        for item in var:
            if "=" not in item:
                err_console.print(
                    f"[red]Error:[/] Invalid --var format: '{item}' (expected key=value)"
                )
                sys.exit(1)
            key, value = item.split("=", 1)
            vars_dict[key] = value
    try:
        # Get project info for display
        project_dir = project.resolve()
        project_file = find_project_file(project_dir)

        if not project_file:
            raise ProjectNotInitializedError(f"No colin.toml found in {project_dir}")

        config = load_project(project_file)
        project_name = config.name
        output_dir = output or config.output_path

        # Handle dry run
        if dry_run:
            dry_result = cast(
                list[tuple[str, Path]],
                await compile_project(
                    project_dir=project,
                    output_dir=output,
                    force=no_cache,
                    ephemeral=ephemeral,
                    dry_run=True,
                ),
            )
            print_project_info(project_file, project_name, output_dir)
            console.print(f"[bold]Would run {len(dry_result)} documents:[/]")
            for uri, _ in dry_result:
                console.print(f"  {uri}")
            return

        # Create state for progress tracking
        state = CompilationState()

        if quiet:
            # No output at all, just run compilation
            result = await compile_project(
                project_dir=project,
                output_dir=output,
                force=no_cache,
                ephemeral=ephemeral,
                dry_run=False,
                state=state,
                vars=vars_dict,
            )
            # Warn about stale config even in quiet mode
            assert isinstance(result, CompileResult)
            stale = sum(
                1
                for doc in result.manifest.documents.values()
                if doc.config_hash and doc.config_hash != result.manifest.config_hash
            )
            if stale > 0:
                err_console.print(
                    f"[yellow]Warning:[/] {stale} document(s) "
                    "compiled with old colin.toml. Run with --no-cache to recompile."
                )
            # Warn about stale output files (only output/, not cache)
            stale_files = get_stale_files(config)
            output_stale = [
                p for p in stale_files if output_dir in p.parents or p.parent == output_dir
            ]
            if output_stale:
                n = len(output_stale)
                try:
                    out_display = output_dir.relative_to(Path.cwd())
                except ValueError:
                    out_display = output_dir
                err_console.print(
                    f"[yellow]Warning:[/] {n} stale {_plural(n, 'file', 'files')} "
                    f"in {out_display}/. Run `colin clean` to remove."
                )
            return

        # Print project info before starting
        print_project_info(project_file, project_name, output_dir)

        # Compile with progress display
        result = await _compile_with_progress(
            project_dir=project,
            output_dir=output,
            force=no_cache,
            ephemeral=ephemeral,
            vars=vars_dict,
            state=state,
        )
        assert isinstance(result, CompileResult)
        stale = sum(
            1
            for doc in result.manifest.documents.values()
            if doc.config_hash and doc.config_hash != result.manifest.config_hash
        )
        if stale > 0:
            console.print()
            console.print(
                f"[yellow]Warning:[/] {stale} document(s) "
                "compiled with old colin.toml. Run with --no-cache to recompile."
            )

        # Warn about stale output files (only output/, not cache)
        stale_files = get_stale_files(config)
        output_stale = [p for p in stale_files if output_dir in p.parents or p.parent == output_dir]
        if output_stale:
            if stale == 0:
                console.print()  # Add spacing if no stale config warning
            n = len(output_stale)
            try:
                out_display = output_dir.relative_to(Path.cwd())
            except ValueError:
                out_display = output_dir
            console.print(
                f"[yellow]Warning:[/] {n} stale {_plural(n, 'file', 'files')} "
                f"in {out_display}/. Run `colin clean` to remove."
            )
            for path in output_stale[:3]:
                try:
                    rel = path.relative_to(output_dir)
                    console.print(f"[yellow]![/] {rel}")
                except ValueError:
                    console.print(f"[yellow]![/] {path}")
            if len(output_stale) > 3:
                console.print(f"[dim]... and {len(output_stale) - 3} more[/]")

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
                # Escape error message to prevent Rich markup interpretation
                escaped_err = str(err).replace("[", r"\[")
                # Indent continuation lines
                lines = escaped_err.split("\n")
                err_console.print(f"  {prefix} [red]✗[/] {lines[0]}")
                for line in lines[1:]:
                    err_console.print(f"        {line}")
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


# Default content for new projects
_DEFAULT_COLIN_TOML = """\
[project]
name = "{name}"
"""

_DEFAULT_HELLO_MD = """\
---
colin: {}
---
# 👋 Welcome to Colin!

This is your first model. Run `colin run` to compile it.
"""


def init(
    project: Path = Path("."),
    *,
    name: str | None = None,
    models: str = "models",
    output: str = "output",
) -> None:
    """Initialize a new Colin project.

    Creates a minimal project with colin.toml and a sample model.

    Args:
        project: Project directory (default: current directory).
        name: Project name (default: directory name).
        models: Source documents directory (default: models).
        output: Compiled output directory (default: output).
    """
    project_dir = project.resolve()
    cwd = Path.cwd()

    # Determine project name
    project_name = name or project_dir.name

    # Check if target already exists
    if (project_dir / "colin.toml").exists():
        err_console.print(f"[red]Error:[/] Project already exists: {project_dir / 'colin.toml'}")
        sys.exit(1)

    try:
        # Create directories
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / models).mkdir(parents=True, exist_ok=True)

        # Build colin.toml content
        toml_lines = ["[project]", f'name = "{project_name}"']
        if models != "models":
            toml_lines.append(f'models = "{models}"')
        if output != "output":
            toml_lines.append(f'output = "{output}"')
        toml_content = "\n".join(toml_lines) + "\n"

        # Write colin.toml
        colin_toml = project_dir / "colin.toml"
        colin_toml.write_text(toml_content)

        # Write hello.md
        hello_md = project_dir / models / "hello.md"
        hello_md.write_text(_DEFAULT_HELLO_MD)

        # Show what was created
        try:
            project_display = project_dir.relative_to(cwd)
        except ValueError:
            project_display = project_dir

        console.print("[dim]Created:[/]")
        if project_dir != cwd:
            console.print(f"[green]→[/green] {project_display}/colin.toml")
            console.print(f"[green]→[/green] {project_display}/{models}/hello.md")
        else:
            console.print("[green]→[/green] colin.toml")
            console.print(f"[green]→[/green] {models}/hello.md")
        console.print()

        if project_dir == cwd:
            run_cmd = "colin run"
        else:
            run_cmd = f"colin run {project_display}"
        console.print(f"[dim]Run `{run_cmd}` to compile your project.[/]")

    except OSError as e:
        err_console.print(f"[red]Error:[/] {e}")
        sys.exit(1)


def clean(
    project: Path = Path("."),
    *,
    all: Annotated[bool, cyclopts.Parameter(name=["--all"])] = False,
    yes: Annotated[bool, cyclopts.Parameter(name=["-y", "--yes"])] = False,
) -> None:
    """Remove build artifacts from the project.

    By default, removes only stale files from output/ (files not tracked by
    the manifest). Use --all to also check .colin/compiled/ for stale files.

    Args:
        project: Project directory (default: current directory).
        all: Also remove stale files from .colin/compiled/.
        yes: Skip confirmation prompt.
    """
    project_file = find_project_file(project.resolve())

    if not project_file:
        err_console.print(f"[red]Error:[/] No colin.toml found in {project.resolve()}")
        err_console.print("[dim]Run `colin init` to create a new project[/]")
        sys.exit(1)

    assert project_file is not None  # narrowing for type checker
    config = load_project(project_file)
    output_dir = config.output_path
    cwd = Path.cwd()

    # Format paths relative to cwd for display
    def format_path(path: Path) -> str:
        try:
            return str(path.relative_to(cwd))
        except ValueError:
            return str(path)

    # Get stale files (include .colin/compiled/ if --all)
    stale_files = get_stale_files(config, include_compiled=all)

    if not stale_files:
        console.print("[dim]Nothing to clean.[/]")
        return

    # Show what will be removed and prompt for confirmation
    if not yes:
        if not sys.stdin.isatty():
            err_console.print("[red]Error:[/] Confirmation required. Use -y to confirm.")
            sys.exit(1)

        print_project_info(project_file, config.name, output_dir)
        console.print("[bold]Will remove stale files:[/]")
        for path in stale_files:
            console.print(f"  [yellow]{format_path(path)}[/]")
        console.print()
        confirm = console.input("[bold]Continue?[/] [dim](y/N)[/] ")
        if confirm.lower() not in ("y", "yes"):
            console.print("[dim]Cancelled.[/]")
            return

    if yes:
        print_project_info(project_file, config.name, output_dir)

    removed = clean_project(config, all=all)

    console.print("[bold]Removed:[/]")
    for path in removed:
        console.print(f"  [dim]{format_path(path)}[/]")
