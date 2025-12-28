"""Run, init, status, and clean commands."""

import asyncio
import sys
from pathlib import Path
from typing import Annotated

import cyclopts
from rich.console import Console
from rich.table import Table

from colin import api
from colin.exceptions import MultipleCompilationErrors, ProjectNotInitializedError

console = Console()
err_console = Console(stderr=True)


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


def run(
    project: Path = Path("."),
    *,
    target: Path | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> None:
    """Compile and run all models.

    Args:
        project: Project directory (default: current directory).
        target: Override target directory (default: from colin.toml).
        force: Force recompile all documents.
        dry_run: Show what would be run without running.
    """
    asyncio.run(_run_async(
        project=project,
        target=target,
        force=force,
        dry_run=dry_run,
    ))


async def _run_async(
    *,
    project: Path,
    target: Path | None,
    force: bool,
    dry_run: bool,
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
        err_console.print(
            f"[dim]{error_count} error(s) in {len(e.errors)} document(s)[/]"
        )
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
