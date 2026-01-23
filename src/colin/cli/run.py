"""Run, init, and clean commands."""

import asyncio
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

import cyclopts
import tomli
import tomli_w
from rich.align import Align
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

import colin
from colin.api.compile import CompileResult, compile_project
from colin.api.manifest import load_manifest
from colin.api.project import (
    VarConfig,
    clean_output_directory,
    clean_project,
    find_project_file,
    get_stale_files,
    get_stale_files_by_project,
    get_stale_files_from_output,
    load_project,
)
from colin.compiler.state import CompilationState, OperationState, Status
from colin.exceptions import MultipleCompilationErrors, ProjectNotInitializedError

console = Console()
err_console = Console(stderr=True)

# Colin logo with cyan-to-blue gradient
# Generated with: npx oh-my-logo "Colin" dawn --filled --block-font tiny --letter-spacing 1 --color
#  █▀▀ █▀█ █    █ █▄ █
#  █▄▄ █▄█ █▄▄  █ █ ▀█
LOGO = (
    "\x1b[38;2;0;198;255m \x1b[38;2;0;193;255m█\x1b[38;2;0;189;255m▀"
    "\x1b[38;2;0;184;255m▀\x1b[38;2;0;179;255m \x1b[38;2;0;175;255m█"
    "\x1b[38;2;0;170;255m▀\x1b[38;2;0;165;255m█\x1b[38;2;0;161;255m "
    "\x1b[38;2;0;156;255m█\x1b[38;2;0;151;255m \x1b[38;2;0;147;255m "
    "\x1b[38;2;0;142;255m \x1b[38;2;0;137;255m█\x1b[38;2;0;133;255m "
    "\x1b[38;2;0;128;255m█\x1b[38;2;0;123;255m▄\x1b[38;2;0;119;255m "
    "\x1b[38;2;0;114;255m█\x1b[39m\n"
    "\x1b[38;2;0;198;255m \x1b[38;2;0;193;255m█\x1b[38;2;0;189;255m▄"
    "\x1b[38;2;0;184;255m▄\x1b[38;2;0;179;255m \x1b[38;2;0;175;255m█"
    "\x1b[38;2;0;170;255m▄\x1b[38;2;0;165;255m█\x1b[38;2;0;161;255m "
    "\x1b[38;2;0;156;255m█\x1b[38;2;0;151;255m▄\x1b[38;2;0;147;255m▄"
    "\x1b[38;2;0;142;255m \x1b[38;2;0;137;255m█\x1b[38;2;0;133;255m "
    "\x1b[38;2;0;128;255m█\x1b[38;2;0;123;255m \x1b[38;2;0;119;255m▀"
    "\x1b[38;2;0;114;255m█\x1b[39m"
)


def _print_banner(
    project_name: str,
    config_path: Path,
    output_dir: Path,
    target: str | None = None,
) -> None:
    """Print the Colin logo banner in a panel with project info."""
    logo_text = Text.from_ansi(LOGO, no_wrap=True)
    version_text = Text(f"Colin {colin.__version__}", style="bold blue")

    # Project info table
    cwd = Path.cwd()
    try:
        config_display = str(config_path.relative_to(cwd))
        output_display = str(output_dir.relative_to(cwd)) + "/"
    except ValueError:
        config_display = str(config_path)
        output_display = str(output_dir) + "/"

    # Show target type if set, otherwise show path
    target_display = target if target else output_display

    info_table = Table.grid(padding=(0, 1))
    info_table.add_column(justify="center")  # emoji
    info_table.add_column(style="cyan", justify="left")  # label
    info_table.add_column(style="dim", justify="left")  # value
    info_table.add_row("📚", "Project:", project_name)
    info_table.add_row("🛠️", "Config:", config_display)
    info_table.add_row("✨", "Target:", target_display)

    docs_url = Text("https://github.com/prefecthq/colin", style="dim")

    panel_content = Group(
        "",
        Align.center(logo_text),
        "",
        "",
        Align.center(version_text),
        Align.center(docs_url),
        "",
        Align.center(info_table),
    )

    panel = Panel(
        panel_content,
        border_style="dim",
        padding=(1, 4),
        width=80,
    )

    console.print(Align.center(panel))
    console.print()


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

    # Sources get left arrow, outputs get right arrow, transforms get checkmark
    if op.name in ("ref", "mcp"):
        return Text("←", style="cyan")
    if op.name in ("ctx", "file"):
        return Text("→", style="green")
    return Text("✓", style="green")


def _make_label(icon: RenderableType, text: RenderableType | str) -> RenderableType:
    """Combine icon and text into a single horizontal renderable."""
    grid = Table.grid(padding=(0, 1))
    grid.add_row(icon, text)
    return grid


def _format_uri(uri: str) -> str:
    """Format a URI for display, stripping project:// prefix."""
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

    return Padding(Group(*trees), (0, 0, 0, 2))  # left indent of 2


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
    config_vars: dict[str, VarConfig] | None = None,
    model_path: Path | None = None,
) -> CompileResult:
    """Compile project with live progress display.

    Args:
        project_dir: Project directory to compile.
        output_dir: Override output directory.
        force: Force recompile.
        ephemeral: Don't write to .colin/.
        vars: Variable overrides.
        state: Compilation state for tracking (created if None).
        config_vars: Variable definitions from config (for showing defaults).

    Returns:
        CompileResult with compiled documents and manifest.
    """
    if state is None:
        state = CompilationState()

    # Show variables section if any are defined
    if config_vars:
        console.print()
        console.print("[cyan bold]Variables[/]")
        console.print()
        for name, var_config in config_vars.items():
            if vars and name in vars:
                # CLI override
                console.print(f"  {name} = {vars[name]}")
            elif var_config.default is not None:
                # Default value
                console.print(f"  {name} = {var_config.default} [dim](default)[/]")
            else:
                # Required but not provided - will error later
                console.print(f"  {name} = [dim italic]<not set>[/]")
        console.print()

    console.print()
    # Show model path relative to cwd, with ~ for home
    if model_path:
        cwd = Path.cwd()
        try:
            model_display = f"~/{model_path.relative_to(Path.home())}/"
        except ValueError:
            try:
                model_display = f"{model_path.relative_to(cwd)}/"
            except ValueError:
                model_display = f"{model_path}/"
        console.print(f"[cyan bold]Compiling...[/] [dim]→ {model_display}[/]")
    else:
        console.print("[cyan bold]Compiling...[/]")

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

    # Show output files (all published, including cached and file outputs)
    assert isinstance(result, CompileResult)

    # Track which outputs are newly compiled vs cached
    recompiled_outputs: set[str] = set()
    for doc in result.compiled:
        if doc.frontmatter.colin.output.should_publish(doc.uri) and doc.output_path:
            recompiled_outputs.add(doc.output_path)
        # Include file outputs from recompiled documents
        for file_path, file_meta in doc.file_output_meta.items():
            should_publish = (
                file_meta.publish
                if file_meta.publish is not None
                else doc.frontmatter.colin.output.should_publish(doc.uri)
            )
            if should_publish:
                recompiled_outputs.add(file_path)

    # Collect all published outputs from manifest (includes cached)
    all_outputs: list[tuple[str, bool]] = []  # (path, is_new)
    for doc_meta in result.manifest.documents.values():
        if doc_meta.is_published and doc_meta.output_path:
            is_new = doc_meta.output_path in recompiled_outputs
            all_outputs.append((doc_meta.output_path, is_new))
        # Include file outputs
        for file_path, file_meta in doc_meta.file_outputs.items():
            should_publish = (
                file_meta.publish if file_meta.publish is not None else doc_meta.is_published
            )
            if should_publish:
                is_new = file_path in recompiled_outputs
                all_outputs.append((file_path, is_new))

    if all_outputs:
        # Format output path for display
        output_display = ""
        if output_dir:
            try:
                output_display = f"~/{output_dir.relative_to(Path.home())}/"
            except ValueError:
                output_display = f"{output_dir}/"

        console.print()
        console.print()
        console.print("[cyan bold]Output Files[/]")
        console.print()

        # Build nested tree structure
        tree: dict[str, Any] = {"files": [], "dirs": {}}
        for path, is_new in all_outputs:
            parts = path.split("/")
            node = tree
            # Navigate to parent directory, creating dirs as needed
            for part in parts[:-1]:
                if part not in node["dirs"]:
                    node["dirs"][part] = {"files": [], "dirs": {}}
                node = node["dirs"][part]
            # Add file to current node
            node["files"].append((parts[-1], is_new))

        def render_tree(node: dict[str, Any], prefix: str = "  ") -> None:
            """Recursively render tree with proper nesting."""
            # Sort files and dirs
            files = sorted(node["files"])
            dirs = sorted(node["dirs"].keys())
            items = [("file", f) for f in files] + [("dir", d) for d in dirs]

            for i, (item_type, item) in enumerate(items):
                is_last = i == len(items) - 1
                branch = "└── " if is_last else "├── "
                continuation = "    " if is_last else "│   "

                if item_type == "file":
                    file_name, is_new = item
                    icon = "[green]✓[/green]" if is_new else "[green]»[/green]"
                    console.print(f"{prefix}[dim]{branch}[/]{icon} {file_name}")
                else:
                    dir_name = item
                    console.print(f"{prefix}[dim]{branch}{dir_name}/[/]")
                    render_tree(node["dirs"][dir_name], prefix + continuation)

        # Show output path as tree root, then render content under it
        if output_display:
            console.print(f"  [dim]{output_display}[/]")
            render_tree(tree, "    ")
        else:
            render_tree(tree, "  ")

    return result


async def run(
    project: Path = Path("."),
    *,
    output: Annotated[Path | None, cyclopts.Parameter(name=["-o", "--output"])] = None,
    no_cache: Annotated[bool, cyclopts.Parameter(name=["--no-cache"])] = False,
    no_clean: Annotated[bool, cyclopts.Parameter(name=["--no-clean"])] = False,
    ephemeral: Annotated[bool, cyclopts.Parameter(name=["--ephemeral"])] = False,
    quiet: Annotated[bool, cyclopts.Parameter(name=["-q", "--quiet"])] = False,
    no_banner: Annotated[bool, cyclopts.Parameter(name=["--no-banner"])] = False,
    var: Annotated[list[str], cyclopts.Parameter(name=["--var"])] = [],
) -> None:
    """Compile and run all models.

    Args:
        project: Project directory (default: current directory).
        output: Override output directory (default: from colin.toml).
        no_cache: Ignore cached results and recompile all documents.
        no_clean: Skip automatic removal of stale output files.
        ephemeral: Don't write to .colin/ directory (for testing, CI, one-off runs).
        quiet: Hide progress display, show only final results.
        no_banner: Hide the Colin logo banner.
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

        # Create state for progress tracking
        state = CompilationState()

        if quiet:
            # No output at all, just run compilation
            result = await compile_project(
                project_dir=project,
                output_dir=output,
                force=no_cache,
                ephemeral=ephemeral,
                state=state,
                vars=vars_dict,
            )
            assert isinstance(result, CompileResult)
            # Auto-clean stale output files (unless --no-clean or custom output)
            if output is None and not no_clean:
                stale_files = get_stale_files(config)
                if stale_files:
                    removed = clean_project(config)
                    if removed:
                        n = len(removed)
                        err_console.print(
                            f"[dim]Cleaned {n} stale {_plural(n, 'file', 'files')}[/]"
                        )
            return

        # Print banner (includes project info) before starting
        if not no_banner:
            _print_banner(project_name, project_file, output_dir, config.output.target)
        else:
            print_project_info(project_file, project_name, output_dir)

        # Compile with progress display
        result = await _compile_with_progress(
            project_dir=project,
            output_dir=output_dir,
            force=no_cache,
            ephemeral=ephemeral,
            vars=vars_dict,
            state=state,
            config_vars=config.vars,
            model_path=config.model_path,
        )
        assert isinstance(result, CompileResult)

        # Auto-clean stale output files (unless --no-clean or custom output)
        if output is None and not no_clean:
            stale_files = get_stale_files(config)
            if stale_files:
                removed = clean_project(config)
                if removed:
                    console.print()
                    n = len(removed)
                    console.print(f"[dim]Cleaned {n} stale {_plural(n, 'file', 'files')}[/]")

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
        # Check if this looks like an output directory
        if (project.resolve() / ".colin-manifest.json").exists():
            err_console.print(
                "[dim]This looks like an output directory. Did you mean `colin update`?[/]"
            )
        else:
            err_console.print("[dim]Run `colin init` to create a new project[/]")
        sys.exit(1)
    except ValueError as e:
        err_console.print(f"[red]Error:[/] {e}")
        sys.exit(1)
    except Exception as e:
        err_console.print(f"[red]Unexpected error:[/] {e}")
        sys.exit(1)


async def update(
    directory: Path = Path("."),
    *,
    no_cache: Annotated[bool, cyclopts.Parameter(name=["--no-cache"])] = False,
    no_clean: Annotated[bool, cyclopts.Parameter(name=["--no-clean"])] = False,
    ephemeral: Annotated[bool, cyclopts.Parameter(name=["--ephemeral"])] = False,
    quiet: Annotated[bool, cyclopts.Parameter(name=["-q", "--quiet"])] = False,
    no_banner: Annotated[bool, cyclopts.Parameter(name=["--no-banner"])] = False,
    var: Annotated[list[str], cyclopts.Parameter(name=["--var"])] = [],
) -> None:
    """Update outputs from their source project.

    Run this command from an output directory (one with .colin-manifest.json)
    to recompile from the original source project.

    Args:
        directory: Output directory to update (default: current directory).
        no_cache: Ignore cached results and recompile all documents.
        no_clean: Skip automatic removal of stale output files.
        ephemeral: Don't write to source project's .colin/ directory.
        quiet: Hide progress display, show only final results.
        no_banner: Hide the Colin logo banner.
        var: Variable overrides in key=value format (overrides stored vars).
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

    target_dir = directory.resolve()

    # Read manifest
    manifest_path = target_dir / ".colin-manifest.json"
    if not manifest_path.exists():
        err_console.print(f"[red]Error:[/] No .colin-manifest.json found in {target_dir}")
        # Check if this looks like a source project
        if (target_dir / "colin.toml").exists():
            err_console.print("[dim]This looks like a source project. Did you mean `colin run`?[/]")
        else:
            err_console.print("[dim]`colin update` requires a Colin output directory[/]")
        sys.exit(1)

    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        err_console.print(f"[red]Error:[/] Invalid JSON in {manifest_path}")
        err_console.print(f"[dim]{e}[/]")
        sys.exit(1)

    project_config = manifest_data.get("project_config")
    stored_vars = manifest_data.get("vars", {})

    if not project_config:
        err_console.print("[red]Error:[/] Manifest missing 'project_config'")
        err_console.print("[dim]Re-run the source project to update the manifest[/]")
        sys.exit(1)

    project_file = Path(project_config)
    if not project_file.exists():
        err_console.print(f"[red]Error:[/] Source project not found: {project_config}")
        sys.exit(1)

    # Determine paths - always output to current directory, not stored output_root
    # (supports moving/copying outputs to new locations like ~/.config/claude/skills)
    project = project_file.parent
    output = target_dir

    # Merge stored vars with CLI overrides (CLI wins)
    if stored_vars:
        if vars_dict:
            stored_vars.update(vars_dict)
        vars_dict = stored_vars

    # Now run compilation (same logic as `run`)
    await run(
        project=project,
        output=output,
        no_cache=no_cache,
        no_clean=True,  # We handle cleaning separately for output directories
        ephemeral=ephemeral,
        quiet=quiet,
        no_banner=no_banner,
        var=[f"{k}={v}" for k, v in vars_dict.items()] if vars_dict else [],
    )

    # Auto-clean stale files from the output directory (unless --no-clean)
    if not no_clean:
        stale_files = get_stale_files_from_output(target_dir)
        if stale_files:
            removed = clean_output_directory(target_dir)
            if removed:
                n = len(removed)
                if quiet:
                    err_console.print(f"[dim]Cleaned {n} stale {_plural(n, 'file', 'files')}[/]")
                else:
                    console.print()
                    console.print(f"[dim]Cleaned {n} stale {_plural(n, 'file', 'files')}[/]")


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


def _get_builtin_blueprints() -> dict[str, Path]:
    """Get built-in blueprint paths."""
    blueprints_dir = Path(__file__).parent.parent / "blueprints"
    if not blueprints_dir.exists():
        return {}
    return {
        d.name: d for d in blueprints_dir.iterdir() if d.is_dir() and (d / "colin.toml").exists()
    }


def _resolve_blueprint(name_or_path: str) -> Path:
    """Resolve a blueprint name or path to an actual path.

    Args:
        name_or_path: Built-in blueprint name or filesystem path.

    Returns:
        Path to the blueprint directory.

    Raises:
        SystemExit: If blueprint not found.
    """
    # Check filesystem path first
    path = Path(name_or_path)
    if path.exists():
        if not (path / "colin.toml").exists():
            err_console.print(f"[red]Error:[/] Not a valid blueprint: {path}")
            err_console.print("[dim]Blueprint directories must contain colin.toml[/]")
            sys.exit(1)
        return path.resolve()

    # Check built-in blueprints
    builtins = _get_builtin_blueprints()
    if name_or_path in builtins:
        return builtins[name_or_path]

    # Not found
    err_console.print(f"[red]Error:[/] Blueprint not found: {name_or_path}")
    if builtins:
        console.print("[dim]Available blueprints:[/]")
        for bp_name, bp_path in sorted(builtins.items()):
            # Try to read description from blueprint.toml
            bp_toml = bp_path / "blueprint.toml"
            description = ""
            if bp_toml.exists():
                data = tomli.loads(bp_toml.read_text())
                description = data.get("blueprint", {}).get("description", "")
            if description:
                # Truncate long descriptions
                if len(description) > 60:
                    description = description[:57] + "..."
                console.print(f"  - [cyan]{bp_name}[/] - {description}")
            else:
                console.print(f"  - [cyan]{bp_name}[/]")
    sys.exit(1)


def _copy_blueprint(blueprint_path: Path, target_dir: Path) -> list[Path]:
    """Copy blueprint files to target directory.

    Args:
        blueprint_path: Source blueprint directory.
        target_dir: Target project directory.

    Returns:
        List of created file paths (relative to target_dir).
    """
    created: list[Path] = []

    for src in blueprint_path.rglob("*"):
        if src.is_file():
            # Skip blueprint metadata
            if src.name == "blueprint.toml":
                continue

            rel_path = src.relative_to(blueprint_path)
            dst = target_dir / rel_path

            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            created.append(rel_path)

    return sorted(created)


def init(
    project: Path = Path("."),
    *,
    name: str | None = None,
    models: str = "models",
    output: str = "output",
    blueprint: Annotated[str | None, cyclopts.Parameter(name=["-b", "--blueprint"])] = None,
    list_blueprints: Annotated[bool, cyclopts.Parameter(name=["--list"])] = False,
    yes: Annotated[bool, cyclopts.Parameter(name=["-y", "--yes"])] = False,
) -> None:
    """Initialize a new Colin project.

    Creates a minimal project with colin.toml and a sample model.

    Args:
        project: Project directory (default: current directory).
        name: Project name (default: directory name).
        models: Source documents directory (default: models).
        output: Compiled output directory (default: output).
        blueprint: Initialize from a blueprint (name or path).
        list_blueprints: List available blueprints and exit.
        yes: Skip confirmation prompt for blueprints.
    """
    # Handle --list
    if list_blueprints:
        builtins = _get_builtin_blueprints()
        if not builtins:
            console.print("[dim]No built-in blueprints available.[/]")
            return

        console.print("[bold]Available blueprints:[/]")
        console.print()
        for bp_name, bp_path in sorted(builtins.items()):
            # Try to read description from blueprint.toml
            bp_toml = bp_path / "blueprint.toml"
            description = ""
            if bp_toml.exists():
                data = tomli.loads(bp_toml.read_text())
                description = data.get("blueprint", {}).get("description", "")

            console.print(f"  [cyan]{bp_name}[/]")
            if description:
                console.print(f"    {description}")
        console.print()
        console.print("[dim]Use: colin init -b <name> [project][/]")
        return

    project_dir = project.resolve()
    cwd = Path.cwd()

    # Determine project name
    project_name = name or project_dir.name

    # Check if target already exists
    if (project_dir / "colin.toml").exists():
        err_console.print(f"[red]Error:[/] Project already exists: {project_dir / 'colin.toml'}")
        sys.exit(1)

    # Check if target is a file (not a directory)
    if project_dir.is_file():
        err_console.print(f"[red]Error:[/] Path exists as a file: {project_dir}")
        sys.exit(1)

    # Check if directory has existing files (guard against accidental overwrites)
    if project_dir.is_dir():
        # Files/directories to ignore when checking if directory is empty
        ignored = {
            ".git",
            ".gitignore",
            ".gitattributes",
            ".venv",
            "venv",
            "__pycache__",
            ".DS_Store",
            ".python-version",
            ".idea",
            ".vscode",
            ".editorconfig",
        }
        existing = [f.name for f in project_dir.iterdir() if f.name not in ignored]
        if existing:
            err_console.print(
                f"[red]Error:[/] Directory is not empty: {project_dir}\n"
                f"  Found: {', '.join(sorted(existing)[:5])}"
                + (f" and {len(existing) - 5} more" if len(existing) > 5 else "")
            )
            err_console.print("\n[dim]Run in an empty directory or specify a new path:[/]")
            err_console.print("  colin init my-project")
            sys.exit(1)

    try:
        if blueprint:
            # Initialize from blueprint
            blueprint_path = _resolve_blueprint(blueprint)

            # Show blueprint info and confirm
            bp_toml = blueprint_path / "blueprint.toml"
            bp_data = {}
            if bp_toml.exists():
                bp_data = tomli.loads(bp_toml.read_text())

            bp_info = bp_data.get("blueprint", {})
            description = bp_info.get("description", "")
            about = bp_info.get("about", "")
            instructions = bp_info.get("instructions", "")

            # Show description and ask for confirmation
            if not yes:
                console.print(f"\n[bold]Blueprint:[/] [cyan]{blueprint}[/]")
                if description:
                    console.print(f"[dim]{description}[/]")
                if about:
                    console.print()
                    console.print(
                        Padding(
                            Panel(
                                Markdown(about.strip()),
                                title="About",
                                title_align="left",
                                border_style="dim",
                                padding=(1, 2),
                                width=min(100, console.width - 4),
                            ),
                            (0, 2),  # margin: top/bottom=0, left/right=2
                        )
                    )
                console.print()
                confirm = console.input("[bold]Initialize project?[/] [dim](Y/n)[/] ")
                if confirm.lower() in ("n", "no"):
                    console.print("[dim]Cancelled.[/]")
                    return

            # Create project directory after confirmation
            project_dir.mkdir(parents=True, exist_ok=True)
            created_files = _copy_blueprint(blueprint_path, project_dir)

            # Update colin.toml with generated project ID
            colin_toml = project_dir / "colin.toml"
            if colin_toml.exists():
                content = tomli.loads(colin_toml.read_text())
                if "project" not in content:
                    content["project"] = {}
                if name:
                    content["project"]["name"] = name
                colin_toml.write_text(tomli_w.dumps(content))

            # Show what was created
            try:
                project_display = project_dir.relative_to(cwd)
            except ValueError:
                project_display = project_dir

            console.print(f"[dim]Created from blueprint '[cyan]{blueprint}[/]':[/]")
            for f in created_files[:10]:  # Show first 10 files
                if project_dir != cwd:
                    console.print(f"[green]→[/green] {project_display}/{f}")
                else:
                    console.print(f"[green]→[/green] {f}")
            if len(created_files) > 10:
                console.print(f"[dim]  ... and {len(created_files) - 10} more files[/]")

            # Show instructions after creation
            if instructions:
                # Prepend cd command if in subdirectory
                if project_dir != cwd:
                    cd_block = f"Navigate to your project:\n\n```bash\ncd {project_display}\n```"
                    instructions = f"{cd_block}\n\n{instructions}"
                console.print()
                console.print(
                    Padding(
                        Panel(
                            Markdown(instructions.strip()),
                            title="Next steps",
                            title_align="left",
                            border_style="dim",
                            padding=(1, 2),
                            width=min(100, console.width - 4),
                        ),
                        (0, 2),  # margin: top/bottom=0, left/right=2
                    )
                )
            elif project_dir != cwd:
                console.print()
                console.print(f"[dim]Run:[/] cd {project_display}")
            return  # Skip generic message

        else:
            # Default initialization
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
    directory: Path = Path("."),
    *,
    all: Annotated[bool, cyclopts.Parameter(name=["--all"])] = False,
    yes: Annotated[bool, cyclopts.Parameter(name=["-y", "--yes"])] = False,
) -> None:
    """Remove stale files from a project or output directory.

    Can be run from:
    - A project directory (with colin.toml) - cleans the project's output
    - An output directory (with .colin-manifest.json) - cleans that directory

    Stale files are those not tracked by any manifest.

    Args:
        directory: Directory to clean (default: current directory).
        all: When in a project, also clean .colin/compiled/.
        yes: Skip confirmation prompt.
    """
    target_dir = directory.resolve()
    cwd = Path.cwd()

    # Format paths relative to cwd for display
    def format_path(path: Path) -> str:
        try:
            return str(path.relative_to(cwd))
        except ValueError:
            return str(path)

    # Determine if this is a project directory or output directory
    project_file = find_project_file(target_dir)

    # Check for manifest at root OR in any subdirectory
    manifest_file = target_dir / ".colin-manifest.json"
    has_manifests = manifest_file.exists() or any(target_dir.rglob(".colin-manifest.json"))

    if project_file:
        # Project mode: use project config
        config = load_project(project_file)
        output_dir = config.output_path
        stale_files = get_stale_files(config, include_compiled=all)

        if not stale_files:
            console.print(f"[dim]Project:[/] {config.name}")
            console.print(f"[dim]Output:[/]  {output_dir}/")
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

    elif has_manifests:
        # Output directory mode: clean using manifests, grouped by project
        stale_by_project = get_stale_files_by_project(target_dir)

        if not stale_by_project:
            console.print(f"[dim]Nothing to clean in {target_dir}/[/]")
            return

        # Flatten for total count
        stale_files = [f for files in stale_by_project.values() for f in files]
        project_count = len(stale_by_project)
        file_count = len(stale_files)

        # Show what will be removed and prompt for confirmation
        if not yes:
            if not sys.stdin.isatty():
                err_console.print("[red]Error:[/] Confirmation required. Use -y to confirm.")
                sys.exit(1)

            console.print(f"[dim]Output directory:[/] {format_path(target_dir)}/")
            console.print(
                f"[dim]Found {file_count} stale {_plural(file_count, 'file', 'files')} "
                f"in {project_count} {_plural(project_count, 'project', 'projects')}[/]"
            )
            console.print()
            console.print("[bold]Will remove stale files:[/]")
            for project_name, files in sorted(stale_by_project.items()):
                console.print(f"  [cyan]{project_name}[/]")
                for path in sorted(files):
                    console.print(f"    [yellow]{format_path(path)}[/]")
            console.print()
            confirm = console.input("[bold]Continue?[/] [dim](y/N)[/] ")
            if confirm.lower() not in ("y", "yes"):
                console.print("[dim]Cancelled.[/]")
                return

        if yes:
            console.print(f"[dim]Output directory:[/] {format_path(target_dir)}/")
            console.print()

        removed = clean_output_directory(target_dir)

    else:
        err_console.print(
            f"[red]Error:[/] No colin.toml or .colin-manifest.json found in {target_dir}"
        )
        err_console.print("[dim]Run from a project directory or output directory[/]")
        sys.exit(1)

    console.print("[bold]Removed:[/]")
    for path in removed:
        console.print(f"  [dim]{format_path(path)}[/]")


def _format_time_ago(dt: datetime) -> str:
    """Format a datetime as a human-readable 'time ago' string."""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    delta = now - dt
    seconds = delta.total_seconds()

    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        mins = int(seconds / 60)
        return f"{mins}m ago"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f"{hours}h ago"
    elif seconds < 604800:
        days = int(seconds / 86400)
        return f"{days}d ago"
    else:
        return dt.strftime("%Y-%m-%d")


def _check_staleness(project_dir: Path, check_refs: bool = True) -> tuple[list[str], list[str]]:
    """Check which documents are stale.

    Args:
        project_dir: Project root directory.
        check_refs: Also check if internal ref targets changed.

    Returns:
        Tuple of (source_changed, ref_stale) lists of relative paths.
    """
    manifest_path = project_dir / ".colin" / "manifest.json"
    if not manifest_path.exists():
        return [], []

    manifest = load_manifest(manifest_path)
    models_dir = project_dir / "models"
    source_changed: list[str] = []
    ref_stale: list[str] = []

    # Build map of uri -> current output_hash for ref checking
    current_hashes: dict[str, str] = {}
    for doc_uri, doc_meta in manifest.documents.items():
        if doc_meta.output_hash:
            current_hashes[doc_uri] = doc_meta.output_hash

    for doc_uri, doc_meta in manifest.documents.items():
        if not doc_uri.startswith("project://"):
            continue

        rel_path = doc_uri[len("project://") :]
        source_path = models_dir / rel_path

        # Check source hash
        if not source_path.exists():
            source_changed.append(rel_path)
            continue

        current_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()[:16]
        if current_hash != doc_meta.source_hash:
            source_changed.append(rel_path)
            continue

        # Check internal refs (project:// refs only)
        if check_refs and doc_meta.ref_versions:
            for ref in doc_meta.refs:
                if ref.provider != "project":
                    continue  # Skip external refs
                ref_path = ref.args.get("path", "")
                ref_uri = f"project://{ref_path}"
                old_version = doc_meta.ref_versions.get(ref.key())
                current_version = current_hashes.get(ref_uri)
                if old_version and current_version and old_version != current_version:
                    ref_stale.append(rel_path)
                    break

    return source_changed, ref_stale


def status(
    directory: Path = Path("."),
    *,
    skip_refs: Annotated[bool, cyclopts.Parameter(name=["--skip-refs"])] = False,
) -> None:
    """Show status of a project or skill.

    Detects whether the directory is a Colin project or a compiled skill,
    and shows relevant information including staleness.

    Args:
        directory: Directory to check (default: current directory).
        skip_refs: Skip ref staleness check (faster, but may miss stale refs).
    """
    target_dir = directory.resolve()

    # Check for project (colin.toml)
    project_file = find_project_file(target_dir)

    # Check for skill/output (.colin-manifest.json)
    manifest_file = target_dir / ".colin-manifest.json"

    if project_file:
        # Project mode
        config = load_project(project_file)
        manifest_path = config.manifest_path

        console.print(f"[cyan]Project:[/] {config.name}")
        console.print(f"[dim]Config:[/]  {project_file}")
        console.print(f"[dim]Output:[/]  {config.output_path}")

        if manifest_path.exists():
            manifest = load_manifest(manifest_path)
            doc_count = len(manifest.documents)

            # Get last compile time
            if manifest.compiled_at:
                compiled_ago = _format_time_ago(manifest.compiled_at)
                console.print(f"[dim]Compiled:[/] {compiled_ago}")
            console.print(f"[dim]Documents:[/] {doc_count}")

            # Check for staleness
            check_refs = not skip_refs
            source_changed, ref_stale = _check_staleness(config.project_root, check_refs=check_refs)

            if source_changed or ref_stale:
                total = len(set(source_changed) | set(ref_stale))
                console.print(f"[yellow]Status:[/] stale ({total} document(s) need recompilation)")
                for path in source_changed[:3]:
                    console.print(f"  [dim]{path}[/] (source changed)")
                for path in ref_stale[:3]:
                    if path not in source_changed:
                        console.print(f"  [dim]{path}[/] (ref changed)")
                shown = len(source_changed[:3]) + len(
                    [p for p in ref_stale[:3] if p not in source_changed]
                )
                if total > shown:
                    console.print(f"  [dim]...and {total - shown} more[/]")
            else:
                console.print("[green]Status:[/] fresh")
        else:
            console.print("[yellow]Status:[/] never compiled")

    elif manifest_file.exists():
        # Skill/output mode
        manifest_data = json.loads(manifest_file.read_text())
        project_name = manifest_data.get("project_name", target_dir.name)
        project_config = manifest_data.get("project_config", "")

        console.print(f"[cyan]Skill:[/] {project_name}")
        console.print(f"[dim]Location:[/] {target_dir}")

        if project_config:
            project_path = Path(project_config)
            # Abbreviate home dir
            try:
                source_str = f"~/{project_path.parent.relative_to(Path.home())}"
            except ValueError:
                source_str = str(project_path.parent)
            console.print(f"[dim]Source:[/] {source_str}")

            # Check staleness
            if project_path.exists():
                project_dir = project_path.parent
                check_refs = not skip_refs
                source_changed, ref_stale = _check_staleness(project_dir, check_refs=check_refs)
                total = len(set(source_changed) | set(ref_stale))
                if total > 0:
                    console.print(
                        f"[yellow]Status:[/] stale ({total} document(s) need recompilation)"
                    )
                else:
                    console.print("[green]Status:[/] fresh")
            else:
                console.print("[yellow]Status:[/] stale (source not found)")
        else:
            console.print("[yellow]Status:[/] no source configured")

        # Show last updated time from manifest file mtime
        try:
            mtime = datetime.fromtimestamp(manifest_file.stat().st_mtime, tz=timezone.utc)
            console.print(f"[dim]Updated:[/] {_format_time_ago(mtime)}")
        except OSError:
            pass

    else:
        err_console.print(
            f"[red]Error:[/] No colin.toml or .colin-manifest.json found in {target_dir}"
        )
        sys.exit(1)
