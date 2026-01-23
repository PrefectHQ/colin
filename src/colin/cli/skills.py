"""Skills management commands."""

import asyncio
import json
import sys
from datetime import datetime, timezone
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


def _check_skill_staleness(manifest_data: dict, project_config_path: Path) -> str | None:
    """Check if a skill is stale by comparing source hashes.

    Returns:
        None if fresh, or a string describing why it's stale.
    """
    if not project_config_path.exists():
        return "source not found"

    # Load project config to get correct paths
    from colin.api.project import load_project

    try:
        config = load_project(project_config_path)
    except Exception:
        return "config unreadable"

    # Use config's manifest path (respects project.manifest-path setting)
    internal_manifest_path = config.manifest_path

    if not internal_manifest_path.exists():
        return "never compiled"

    try:
        internal_manifest = json.loads(internal_manifest_path.read_text())
    except (json.JSONDecodeError, OSError):
        return "manifest unreadable"

    # Compare source hashes from internal manifest to current source files
    internal_docs = internal_manifest.get("documents", {})

    # Use config's model path (respects project.model-path setting)
    models_dir = config.model_path

    # Check if any source file has changed
    for doc_uri, doc_meta in internal_docs.items():
        if not isinstance(doc_meta, dict):
            continue

        stored_hash = doc_meta.get("source_hash")
        if not stored_hash:
            continue

        # Reconstruct source path from URI
        # URI format: project://path/to/doc.md
        if doc_uri.startswith("project://"):
            rel_path = doc_uri[len("project://") :]
            source_path = models_dir / rel_path

            if source_path.exists():
                import hashlib

                current_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()[:16]
                if current_hash != stored_hash:
                    return "sources changed"

    return None


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


@app.command(name="list")
def list_skills(
    directory: Path | None = None,
) -> None:
    """List all Colin skills and their status.

    Shows installed skills, their source projects, and whether they're stale.

    Args:
        directory: Skills directory (default: ~/.claude/skills).
    """
    skills_dir = directory or _default_skills_dir()

    if not skills_dir.exists():
        err_console.print(f"[red]Error:[/] Skills directory not found: {skills_dir}")
        sys.exit(1)

    if not skills_dir.is_dir():
        err_console.print(f"[red]Error:[/] Not a directory: {skills_dir}")
        sys.exit(1)

    # Find all manifests - both at root level and in subdirectories
    skills: list[tuple[str, dict, Path]] = []

    # Check root-level manifest (skill outputs to subdirs but manifest at root)
    root_manifest = skills_dir / ".colin-manifest.json"
    if root_manifest.exists():
        try:
            manifest_data = json.loads(root_manifest.read_text())
            name = manifest_data.get("project_name", "unknown")
            skills.append((name, manifest_data, root_manifest))
        except (json.JSONDecodeError, OSError):
            pass

    # Check subdirectories for their own manifests
    for item in skills_dir.iterdir():
        if item.is_dir():
            manifest_path = item / ".colin-manifest.json"
            if manifest_path.exists():
                try:
                    manifest_data = json.loads(manifest_path.read_text())
                    name = manifest_data.get("project_name", item.name)
                    skills.append((name, manifest_data, manifest_path))
                except (json.JSONDecodeError, OSError):
                    skills.append((item.name, {}, manifest_path))

    if not skills:
        console.print(f"[dim]No Colin skills found in {skills_dir}[/]")
        return

    # Sort by name
    skills.sort(key=lambda x: x[0])

    for name, manifest_data, manifest_path in skills:
        # Get skill location (where the manifest lives)
        skill_location = manifest_path.parent
        # Get project info
        project_config = manifest_data.get("project_config", "")
        project_path = Path(project_config) if project_config else None

        # Check staleness
        if project_path:
            stale_reason = _check_skill_staleness(manifest_data, project_path)
        else:
            stale_reason = "no source"

        if stale_reason:
            status = f"[yellow]stale[/] ({stale_reason})"
        else:
            status = "[green]fresh[/]"

        # Get last updated time from manifest file
        try:
            mtime = datetime.fromtimestamp(manifest_path.stat().st_mtime, tz=timezone.utc)
            updated = _format_time_ago(mtime)
        except OSError:
            updated = "unknown"

        # Format location (abbreviate home dir)
        try:
            location_str = str(skill_location.relative_to(Path.home()))
            location_str = f"~/{location_str}"
        except ValueError:
            location_str = str(skill_location)

        # Format source path (abbreviate home dir)
        if project_path:
            try:
                source_str = str(project_path.parent.relative_to(Path.home()))
                source_str = f"~/{source_str}"
            except ValueError:
                source_str = str(project_path.parent)
        else:
            source_str = "-"

        # Print skill entry
        console.print(f"[cyan]{name}[/]")
        console.print(f"  [dim]Status:[/]   {status} ({updated})")
        console.print(f"  [dim]Location:[/] {location_str}")
        console.print(f"  [dim]Source:[/]   {source_str}")
        console.print()
