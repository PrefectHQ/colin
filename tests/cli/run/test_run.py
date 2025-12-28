"""Tests for colin run and clean commands."""

from collections.abc import Callable
from pathlib import Path


def test_run_creates_output(
    test_project: Path, target_dir: Path, mock_agent, cli: Callable[..., None]
):
    """colin run creates compiled output files."""
    cli("run", "--target", str(target_dir), "--quiet")

    assert (target_dir / "compiled" / "greeting.md").exists()


def test_clean_removes_target(test_project: Path, mock_agent, cli: Callable[..., None]):
    """colin clean removes target/ contents after compilation."""
    project_target = test_project / "target"

    # Run to create output
    cli("run", "--quiet")
    assert (project_target / "compiled").exists()

    # Clean
    cli("clean", "--yes")
    assert not (project_target / "compiled").exists()


def test_clean_does_nothing_if_no_target(tmp_path: Path, monkeypatch, cli: Callable[..., None]):
    """colin clean does nothing if target doesn't exist."""
    monkeypatch.chdir(tmp_path)

    cli("init")

    # Clean should not error even if target doesn't exist
    cli("clean", "--yes")
