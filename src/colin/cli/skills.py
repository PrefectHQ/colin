"""Skills management commands."""

import asyncio
import sys
from pathlib import Path

import cyclopts
from rich.console import Console

from colin.cli.run import update as run_update

console = Console()
err_console = Console(stderr=True)

app = cyclopts.App(name="skills", help="Manage Colin skills.")


def _default_skills_dir() -> Path:
    """Get the default skills directory for Claude."""
    # Claude's skills directory on macOS/Linux
    # TODO: Add Windows support if needed
    return Path.home() / ".claude" / "skills"


@app.command
async def update(
    directory: Path | None = None,
    *,
    no_cache: bool = False,
    quiet: bool = False,
) -> None:
    """Update all Colin skills in a directory.

    Scans the directory for subdirectories with .colin-manifest.json
    and runs `colin update` on each in parallel.

    Args:
        directory: Skills directory (default: ~/.claude/skills).
        no_cache: Ignore cached results and recompile all documents.
        quiet: Hide progress display, show only final results.
    """
    skills_dir = directory or _default_skills_dir()

    if not skills_dir.exists():
        err_console.print(f"[red]Error:[/] Skills directory not found: {skills_dir}")
        sys.exit(1)

    if not skills_dir.is_dir():
        err_console.print(f"[red]Error:[/] Not a directory: {skills_dir}")
        sys.exit(1)

    # Find all subdirectories with manifests
    skill_dirs: list[Path] = []
    for item in skills_dir.iterdir():
        if item.is_dir() and (item / ".colin-manifest.json").exists():
            skill_dirs.append(item)

    if not skill_dirs:
        console.print(f"[dim]No Colin skills found in {skills_dir}[/]")
        return

    if not quiet:
        console.print(f"[dim]Updating {len(skill_dirs)} skill(s) in {skills_dir}[/]")
        console.print()

    # Run updates in parallel
    async def update_skill(skill_dir: Path) -> tuple[Path, bool, str | None]:
        """Update a single skill, return (path, success, error_msg)."""
        try:
            await run_update(
                directory=skill_dir,
                no_cache=no_cache,
                quiet=True,  # Always quiet for parallel runs
                no_banner=True,
            )
            return (skill_dir, True, None)
        except SystemExit:
            return (skill_dir, False, "Update failed")
        except Exception as e:
            return (skill_dir, False, str(e))

    results = await asyncio.gather(*[update_skill(d) for d in skill_dirs])

    # Report results
    succeeded = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)

    if not quiet:
        for skill_dir, ok, error in results:
            name = skill_dir.name
            if ok:
                console.print(f"[green]✓[/] {name}")
            else:
                console.print(f"[red]✗[/] {name}: {error}")

        console.print()

    if failed:
        console.print(f"[green]{succeeded}[/] updated, [red]{failed}[/] failed")
        sys.exit(1)
    else:
        console.print(f"[green]{succeeded}[/] skill(s) updated")
