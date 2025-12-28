"""Fixtures for CLI tests."""

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from rich.console import Console

from colin.cli import app as _app
from colin.cli.run import init


@pytest.fixture
def project(tmp_path: Path, monkeypatch) -> Path:
    """Create a minimal project and cd into it."""
    init(project=tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def test_project(request: pytest.FixtureRequest, tmp_path: Path, monkeypatch) -> Path:
    """Copy the collocated project/ to tmp_path and chdir into it.

    Discovers project/ relative to the test file requesting this fixture.
    """
    test_file = request.path
    source_project = test_file.parent / "project"

    if not source_project.exists():
        pytest.skip(f"No project/ directory found at {source_project}")

    # Copy to tmp_path
    dest_project = tmp_path / "project"
    shutil.copytree(source_project, dest_project)

    # Change to project directory so CLI commands work
    monkeypatch.chdir(dest_project)

    return dest_project


@pytest.fixture
def target_dir(tmp_path: Path) -> Path:
    """Return a clean target directory for compilation output."""
    target = tmp_path / "target"
    target.mkdir()
    return target


@pytest.fixture
def console() -> Console:
    """Create a console with fixed settings for predictable test output."""
    return Console(
        width=70,
        force_terminal=True,
        highlight=False,
        color_system=None,
        legacy_windows=False,
    )


@pytest.fixture
def cli() -> Callable[..., None]:
    """Return a CLI runner that doesn't exit on success.

    Usage:
        cli("mcp", "add", "server", "--command", "python")
        cli("run", "--quiet")
    """

    def run(*args: str) -> None:
        _app(list(args), result_action="return_value")

    return run
