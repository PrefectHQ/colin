"""Shared fixtures for e2e tests."""

import shutil
from pathlib import Path

import pytest


@pytest.fixture
def e2e_project(request: pytest.FixtureRequest, tmp_path: Path) -> Path:
    """Copy the collocated project/ to tmp_path and return path to it.

    Discovers project/ relative to the test file requesting this fixture.
    """
    test_file = request.path
    source_project = test_file.parent / "project"

    if not source_project.exists():
        pytest.skip(f"No project/ directory found at {source_project}")

    # Copy to tmp_path
    dest_project = tmp_path / "project"
    shutil.copytree(source_project, dest_project)
    return dest_project


@pytest.fixture
def target_dir(tmp_path: Path) -> Path:
    """Return a clean target directory for compilation output."""
    target = tmp_path / "target"
    target.mkdir()
    return target
