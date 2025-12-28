"""Tests for ref() resolution."""

from collections.abc import Callable
from pathlib import Path

import pytest

from colin.cli import app


def test_ref_content_propagates(
    test_project: Path, target_dir: Path, mock_agent, cli: Callable[..., None]
):
    """Content from referenced doc appears in output."""
    cli("run", "--target", str(target_dir), "--quiet")

    welcome = (target_dir / "compiled" / "welcome.md").read_text()
    assert "Hello from greeting!" in welcome


def test_dependency_order(
    test_project: Path, target_dir: Path, mock_agent, cli: Callable[..., None]
):
    """Documents compile in dependency order."""
    cli("run", "--target", str(target_dir), "--quiet")

    summary = (target_dir / "compiled" / "summary.md").read_text()
    assert "Hello from greeting!" in summary
    assert "Welcome to Colin" in summary


def test_all_outputs_created(
    test_project: Path, target_dir: Path, mock_agent, cli: Callable[..., None]
):
    """All documents are compiled to output."""
    cli("run", "--target", str(target_dir), "--quiet")

    assert (target_dir / "compiled" / "greeting.md").exists()
    assert (target_dir / "compiled" / "welcome.md").exists()
    assert (target_dir / "compiled" / "summary.md").exists()


def test_missing_ref_fails(test_project: Path, target_dir: Path, mock_agent):
    """Referencing a non-existent document produces an error."""
    # Add a file with a bad ref
    models_dir = test_project / "models"
    (models_dir / "bad.md").write_text("""\
---
name: Bad
---
{{ ref('nonexistent').content }}
""")

    with pytest.raises(SystemExit) as exc_info:
        app(["run", "--target", str(target_dir), "--quiet"])

    assert exc_info.value.code == 1
