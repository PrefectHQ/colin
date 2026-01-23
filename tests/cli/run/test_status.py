"""Tests for colin status command."""

import json
from collections.abc import Callable
from pathlib import Path


def test_status_project_never_compiled(test_project: Path, cli: Callable[..., None], capsys):
    """colin status shows 'never compiled' for new projects."""
    cli("status")

    captured = capsys.readouterr()
    assert "refs-test" in captured.out  # Project name from fixture
    assert "never compiled" in captured.out


def test_status_project_fresh(test_project: Path, mock_agent, cli: Callable[..., None], capsys):
    """colin status shows 'fresh' for just-compiled projects."""
    # Compile first
    cli("run", "--quiet")

    # Check status
    cli("status")

    captured = capsys.readouterr()
    assert "refs-test" in captured.out
    # Should not show "stale" - might show "fresh" explicitly or just no stale indicator
    assert "stale" not in captured.out.lower() or "fresh" in captured.out.lower()


def test_status_project_stale_source(
    test_project: Path, mock_agent, cli: Callable[..., None], capsys
):
    """colin status detects when source files have changed."""
    # Compile first
    cli("run", "--quiet")

    # Modify a source file
    (test_project / "models" / "greeting.md").write_text("# Changed content")

    # Check status
    cli("status")

    captured = capsys.readouterr()
    assert "stale" in captured.out
    assert "source changed" in captured.out


def test_status_skill_fresh(
    test_project: Path, mock_agent, cli: Callable[..., None], tmp_path: Path, capsys
):
    """colin status shows 'fresh' for just-compiled skill."""
    skill_dir = tmp_path / "my-skill"
    cli("run", "--quiet", "--output", str(skill_dir))

    # Check status from skill directory
    cli("status", str(skill_dir))

    captured = capsys.readouterr()
    assert "refs-test" in captured.out  # Project name
    assert "fresh" in captured.out


def test_status_skill_stale(
    test_project: Path, mock_agent, cli: Callable[..., None], tmp_path: Path, capsys
):
    """colin status detects stale skills when source changes."""
    skill_dir = tmp_path / "my-skill"
    cli("run", "--quiet", "--output", str(skill_dir))

    # Modify source
    (test_project / "models" / "greeting.md").write_text("# Changed")

    # Check status
    cli("status", str(skill_dir))

    captured = capsys.readouterr()
    assert "stale" in captured.out


def test_status_skill_missing_source(tmp_path: Path, cli: Callable[..., None], capsys):
    """colin status handles skills with missing source projects."""
    skill_dir = tmp_path / "orphan-skill"
    skill_dir.mkdir()
    (skill_dir / ".colin-manifest.json").write_text(
        json.dumps(
            {
                "project_name": "orphan",
                "project_config": "/nonexistent/colin.toml",
                "files": {},
            }
        )
    )

    cli("status", str(skill_dir))

    captured = capsys.readouterr()
    assert "orphan" in captured.out
    assert "stale" in captured.out
    assert "source not found" in captured.out


def test_status_no_project(tmp_path: Path, cli: Callable[..., None], capsys):
    """colin status errors on directories without project or manifest."""
    try:
        cli("status", str(tmp_path))
    except SystemExit as e:
        assert e.code == 1

    captured = capsys.readouterr()
    assert "No colin.toml" in captured.err


def test_status_skip_refs_flag(test_project: Path, mock_agent, cli: Callable[..., None], capsys):
    """colin status --skip-refs skips ref checking."""
    cli("run", "--quiet")

    # This should work without errors
    cli("status", "--skip-refs")

    captured = capsys.readouterr()
    assert "refs-test" in captured.out
