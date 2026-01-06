"""Run, init, and clean commands."""

import asyncio
import contextlib
import importlib.resources
import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, cast

import cyclopts
import tomli
import tomli_w
from jinja2 import Environment
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.prompt import Prompt
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from colin import api
from colin.compiler.state import CompilationState, OperationState, Status
from colin.exceptions import MultipleCompilationErrors, ProjectNotInitializedError

if TYPE_CHECKING:
    from colin.api.project import ProjectConfig

BUILTIN_TEMPLATES = ("blank", "basic", "quickstart")


@contextlib.contextmanager
def _null_context(value: Path):
    """Context manager that just yields the value unchanged."""
    yield value


console = Console()
err_console = Console(stderr=True)


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


def prompt_for_missing_vars(
    config: "ProjectConfig",
    vars_dict: dict[str, str] | None,
    interactive: bool = True,
) -> dict[str, str]:
    """Prompt for variables that have prompt text but no value.

    Args:
        config: Project configuration with variable definitions.
        vars_dict: CLI-provided variable values.
        interactive: Whether interactive prompting is allowed.

    Returns:
        Updated variables dict with prompted values.
    """
    result = dict(vars_dict) if vars_dict else {}

    # Collect variables that need prompting
    to_prompt: list[tuple[str, str, str | None]] = []  # (name, prompt_text, default)
    for name, var_config in config.vars.items():
        if name in result or os.environ.get(f"COLIN_VAR_{name.upper()}"):
            continue
        if interactive and var_config.prompt:
            default = str(var_config.default) if var_config.default is not None else None
            to_prompt.append((name, var_config.prompt, default))

    if to_prompt:
        console.print()
        console.print("[dim]Variables:[/]")
        for name, prompt_text, default in to_prompt:
            value = Prompt.ask(f"  [bold]{prompt_text}[/]", default=default)
            if value:
                result[name] = value
        console.print()

    return result


def print_project_info(project_file: Path, project_name: str, output_dir: Path) -> None:
    """Print project info header used by multiple commands."""
    cwd = Path.cwd()
    try:
        config_display = project_file.relative_to(cwd)
        output_display = output_dir.relative_to(cwd)
    except ValueError:
        config_display = project_file
        output_display = output_dir

    console.print(f"[dim]Config:[/]  {config_display}")
    console.print(f"[dim]Project:[/] {project_name}")
    console.print(f"[dim]Output:[/]  {output_display}/")
    console.print()


async def run(
    project: Path = Path("."),
    *,
    output: Annotated[Path | None, cyclopts.Parameter(name=["-o", "--output"])] = None,
    no_cache: Annotated[bool, cyclopts.Parameter(name=["--no-cache"])] = False,
    dry_run: bool = False,
    quiet: Annotated[bool, cyclopts.Parameter(name=["-q", "--quiet"])] = False,
    no_interactive: Annotated[bool, cyclopts.Parameter(name=["--no-interactive"])] = False,
    var: Annotated[list[str], cyclopts.Parameter(name=["--var"])] = [],
) -> None:
    """Compile and run all models.

    Args:
        project: Project directory (default: current directory).
        output: Override output directory (default: from colin.toml).
        no_cache: Ignore cached results and recompile all documents.
        dry_run: Show what would be run without running.
        quiet: Hide progress display, show only final results.
        no_interactive: Disable interactive prompts (for CI/automation).
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
        from colin.api.project import find_project_file, load_project

        project_dir = project.resolve()
        project_file = find_project_file(project_dir)

        if not project_file:
            raise ProjectNotInitializedError(f"No colin.toml found in {project_dir}")

        config = load_project(project_file)
        project_name = config.name
        output_dir = output or config.output_path

        # Prompt for missing variables (if interactive and prompts configured)
        interactive = (
            not no_interactive and not os.environ.get("COLIN_NO_INTERACTIVE") and sys.stdin.isatty()
        )
        vars_dict = prompt_for_missing_vars(
            config,
            vars_dict,
            interactive=interactive,
        )

        # Handle dry run
        if dry_run:
            dry_result = cast(
                list[tuple[str, Path]],
                await api.compile_project(
                    project_dir=project,
                    output_dir=output,
                    force=no_cache,
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
            await api.compile_project(
                project_dir=project,
                output_dir=output,
                force=no_cache,
                dry_run=False,
                state=state,
                vars=vars_dict,
            )
            # Warn about stale config even in quiet mode
            if result.stale_config_count > 0:
                err_console.print(
                    f"[yellow]Warning:[/] {result.stale_config_count} document(s) "
                    "compiled with old colin.toml. Run with --no-cache to recompile."
                )
            return

        # Print project info before starting
        print_project_info(project_file, project_name, output_dir)

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
                    output_dir=output,
                    force=no_cache,
                    dry_run=False,
                    state=state,
                    vars=vars_dict,
                )
            )
            while not task.done():
                live.update(render_state(state), refresh=True)
                await asyncio.sleep(0.1)
            # Final update before exiting Live context
            live.update(render_state(state), refresh=True)

        # Get the result and check for stale config warning
        result = await task
        if result.stale_config_count > 0:
            console.print()
            console.print(
                f"[yellow]Warning:[/] {result.stale_config_count} document(s) "
                "compiled with old colin.toml. Run with --no-cache to recompile."
            )

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


def _resolve_template(template: str) -> Path:
    """Resolve a template name or path to an actual directory.

    Args:
        template: Either a built-in template name or a path to a directory.

    Returns:
        Path to the template directory.

    Raises:
        ValueError: If the template cannot be found.
    """
    template_path = Path(template)

    # If it exists as a directory, use it directly
    if template_path.is_dir():
        return template_path.resolve()

    # Otherwise, look for a built-in template
    if template not in BUILTIN_TEMPLATES:
        available = ", ".join(BUILTIN_TEMPLATES)
        raise ValueError(
            f"Template '{template}' not found. "
            f"Built-in templates: {available}. "
            f"Or provide a path to a template directory."
        )

    # Load from package resources
    templates_pkg = importlib.resources.files("colin.cli.templates")
    template_dir = templates_pkg / template

    # Convert to a real path (may extract if in a zip)
    with importlib.resources.as_file(template_dir) as path:
        if not path.is_dir():
            raise ValueError(f"Built-in template '{template}' is missing or invalid")
        # Return a copy since as_file context may clean up
        return path


def _prompt_for_template_vars(
    colin_toml: Path,
    project_name: str,
    interactive: bool,
) -> dict[str, str]:
    """Read template's colin.toml and prompt for variables with prompts defined.

    Args:
        colin_toml: Path to the template's colin.toml.
        project_name: Default project name (from directory).
        interactive: Whether to prompt interactively.

    Returns:
        Dictionary of variable values.
    """
    result: dict[str, str] = {"project_name": project_name}

    if not colin_toml.exists():
        return result

    with open(colin_toml, "rb") as f:
        data = tomli.load(f)

    vars_config = data.get("vars", {})

    to_prompt: list[tuple[str, str, str | None]] = []
    for name, config in vars_config.items():
        if not isinstance(config, dict):
            continue
        prompt_text = config.get("prompt")
        if not prompt_text:
            continue
        default = config.get("default")
        if default is not None:
            default = str(default)
        # Use project_name as default for project_name var
        if name == "project_name" and default is None:
            default = project_name
        to_prompt.append((name, prompt_text, default))

    if to_prompt and interactive:
        console.print()
        for name, prompt_text, default in to_prompt:
            value = Prompt.ask(f"  [bold]{prompt_text}[/]", default=default)
            if value:
                result[name] = value
        console.print()
    elif to_prompt:
        # Non-interactive: use defaults
        for name, _, default in to_prompt:
            if default:
                result[name] = default

    return result


def _copy_template(
    template_dir: Path,
    target_dir: Path,
    variables: dict[str, str],
) -> list[Path]:
    """Copy template files to target, rendering Jinja expressions in config files.

    Only .toml files are rendered with Jinja substitution. Model files (.md)
    contain colin runtime syntax and are copied as-is.

    Args:
        template_dir: Source template directory.
        target_dir: Target project directory.
        variables: Variables for Jinja rendering.

    Returns:
        List of created files/directories.
    """
    created: list[Path] = []
    env = Environment(autoescape=False)

    # Build Jinja context - support both {{ project_name }} and {{ vars.project_name }}
    jinja_context = dict(variables)
    jinja_context["vars"] = variables

    for src_path in template_dir.rglob("*"):
        rel_path = src_path.relative_to(template_dir)
        dest_path = target_dir / rel_path

        if src_path.is_dir():
            dest_path.mkdir(parents=True, exist_ok=True)
            created.append(dest_path)
        elif src_path.is_file():
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            # Only render .toml files with Jinja - model files contain colin
            # runtime syntax that should be preserved
            if src_path.suffix == ".toml":
                content = src_path.read_text()
                template = env.from_string(content)
                rendered = template.render(**jinja_context)
                dest_path.write_text(rendered)
            else:
                # Copy other files as-is
                shutil.copy2(src_path, dest_path)

            created.append(dest_path)

    return created


def _update_colin_toml_paths(
    colin_toml: Path,
    models: str | None,
    output: str | None,
) -> None:
    """Update model-path and output-path in colin.toml.

    Args:
        colin_toml: Path to colin.toml file.
        models: New model-path value, or None to keep existing.
        output: New output-path value, or None to keep existing.
    """
    with open(colin_toml, "rb") as f:
        data = tomli.load(f)

    if "project" not in data:
        data["project"] = {}

    if models:
        data["project"]["model-path"] = models
    if output:
        data["project"]["output-path"] = output

    with open(colin_toml, "wb") as f:
        tomli_w.dump(data, f)


def init(
    project: Path = Path("."),
    *,
    name: str | None = None,
    template: Annotated[str, cyclopts.Parameter(name=["-t", "--template"])] = "basic",
    models: str | None = None,
    output: str | None = None,
    no_interactive: Annotated[bool, cyclopts.Parameter(name=["--no-interactive"])] = False,
) -> None:
    """Initialize a new Colin project.

    Creates a project from a template, prompting for variables if needed.

    Args:
        project: Project directory (default: current directory).
        name: Project name (default: directory name).
        template: Template to use (built-in: blank, basic, quickstart; or a path).
        models: Override model path from template.
        output: Override output path from template.
        no_interactive: Disable interactive prompts (for CI/automation).
    """
    project_dir = project.resolve()
    project_name = name or project_dir.name

    # Check if project already exists
    colin_toml = project_dir / "colin.toml"
    if colin_toml.exists():
        err_console.print(f"[red]Error:[/] Project already exists: {colin_toml}")
        sys.exit(1)

    # Resolve template
    try:
        template_dir = _resolve_template(template)
    except ValueError as e:
        err_console.print(f"[red]Error:[/] {e}")
        sys.exit(1)

    # Determine if interactive
    interactive = (
        not no_interactive and not os.environ.get("COLIN_NO_INTERACTIVE") and sys.stdin.isatty()
    )

    # Prompt for template variables
    template_colin_toml = template_dir / "colin.toml"
    variables = _prompt_for_template_vars(template_colin_toml, project_name, interactive)

    # Copy template to target
    project_dir.mkdir(parents=True, exist_ok=True)

    # Use as_file context for package resources
    with (
        importlib.resources.as_file(importlib.resources.files("colin.cli.templates") / template)
        if template in BUILTIN_TEMPLATES
        else _null_context(template_dir) as tpl_path
    ):
        created = _copy_template(tpl_path, project_dir, variables)

    # Apply --models and --output overrides after template copy
    if models or output:
        _update_colin_toml_paths(project_dir / "colin.toml", models, output)

    # Display results
    cwd = Path.cwd()
    console.print()
    for path in sorted(created):
        if path.is_file():
            try:
                display = path.relative_to(cwd)
            except ValueError:
                display = path
            console.print(f"[green]Created:[/] {display}")

    console.print()
    # Show appropriate run command based on where project was created
    if project_dir == cwd:
        console.print("[dim]Run `colin run` to compile your project[/]")
    else:
        try:
            rel_path = project_dir.relative_to(cwd)
            console.print(f"[dim]Run `colin run {rel_path}` to compile your project[/]")
        except ValueError:
            console.print(f"[dim]Run `colin run {project_dir}` to compile your project[/]")


def clean(
    project: Path = Path("."),
    *,
    yes: Annotated[bool, cyclopts.Parameter(name=["-y", "--yes"])] = False,
    no_interactive: Annotated[bool, cyclopts.Parameter(name=["--no-interactive"])] = False,
) -> None:
    """Remove output directory (compiled outputs and manifest).

    Args:
        project: Project directory (default: current directory).
        yes: Skip confirmation prompt.
        no_interactive: Disable interactive prompts (for CI/automation).
    """
    status_info = api.get_project_status(project)
    project_file = status_info["project_file"]
    output_dir = status_info["output_dir"]

    if not project_file:
        err_console.print(f"[red]Error:[/] No colin.toml found in {project.resolve()}")
        err_console.print("[dim]Run `colin init` to create a new project[/]")
        sys.exit(1)

    if not output_dir.exists():
        console.print("[dim]Nothing to clean.[/]")
        return

    # Collect files for display
    files_in_output: list[str] = []
    project_dir = project.resolve()
    for path in output_dir.rglob("*"):
        if path.is_file():
            try:
                rel = path.relative_to(project_dir)
                files_in_output.append(str(rel))
            except ValueError:
                files_in_output.append(str(path))

    # Show what will be removed
    if not yes:
        # Check if we can prompt
        interactive = (
            not no_interactive and not os.environ.get("COLIN_NO_INTERACTIVE") and sys.stdin.isatty()
        )
        if not interactive:
            err_console.print("[red]Error:[/] Confirmation required. Use -y to confirm.")
            sys.exit(1)

        print_project_info(project_file, status_info["project_name"], output_dir)
        console.print("[bold]Will remove:[/]")
        for rel in files_in_output:
            console.print(f"  [yellow]{rel}[/]")
        console.print()
        confirm = console.input("[bold]Continue?[/] [dim](y/N)[/] ")
        if confirm.lower() not in ("y", "yes"):
            console.print("[dim]Cancelled.[/]")
            return

    # Show project info if skipping confirmation
    if yes:
        print_project_info(project_file, status_info["project_name"], output_dir)

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
