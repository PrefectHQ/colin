"""Tests for colin skills commands."""

import json
from collections.abc import Callable
from pathlib import Path


def test_skills_update_no_skills(tmp_path: Path, cli: Callable[..., None], capsys):
    """colin skills update reports no skills when directory is empty."""
    cli("skills", "update", str(tmp_path))

    captured = capsys.readouterr()
    assert "No Colin skills found" in captured.out


def test_skills_update_nonexistent_directory(cli: Callable[..., None], capsys):
    """colin skills update errors on nonexistent directory."""
    try:
        cli("skills", "update", "/nonexistent/path")
    except SystemExit as e:
        assert e.code == 1

    captured = capsys.readouterr()
    assert "Skills directory not found" in captured.err


def test_skills_update_updates_skills(
    test_project: Path, mock_agent, cli: Callable[..., None], tmp_path: Path, capsys
):
    """colin skills update updates all skills with manifests."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    # Create a skill by running colin to an output directory
    skill_output = skills_dir / "my-skill"
    cli("run", "--quiet", "--output", str(skill_output))

    # Verify manifest was created
    manifest_path = skill_output / ".colin-manifest.json"
    assert manifest_path.exists()

    # Run skills update
    cli("skills", "update", str(skills_dir))

    captured = capsys.readouterr()
    assert "my-skill" in captured.out
    assert "1" in captured.out  # "1 skill(s) updated"


def test_skills_update_skips_non_colin_directories(
    test_project: Path, mock_agent, cli: Callable[..., None], tmp_path: Path, capsys
):
    """colin skills update skips directories without manifests."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    # Create a non-Colin directory (just a regular directory)
    (skills_dir / "not-a-skill").mkdir()
    (skills_dir / "not-a-skill" / "README.md").write_text("Not a skill")

    # Create a Colin skill
    skill_output = skills_dir / "real-skill"
    cli("run", "--quiet", "--output", str(skill_output))

    # Run skills update
    cli("skills", "update", str(skills_dir))

    captured = capsys.readouterr()
    assert "real-skill" in captured.out
    assert "not-a-skill" not in captured.out
    assert "1" in captured.out  # Only 1 skill updated


def test_skills_update_multiple_skills(
    test_project: Path, mock_agent, cli: Callable[..., None], tmp_path: Path, capsys
):
    """colin skills update handles multiple skills in parallel."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    # Create multiple skills
    for name in ["skill-a", "skill-b", "skill-c"]:
        skill_output = skills_dir / name
        cli("run", "--quiet", "--output", str(skill_output))

    # Run skills update
    cli("skills", "update", str(skills_dir))

    captured = capsys.readouterr()
    assert "skill-a" in captured.out
    assert "skill-b" in captured.out
    assert "skill-c" in captured.out
    assert "3" in captured.out  # "3 skill(s) updated"


def test_skills_update_reports_failures(
    test_project: Path, mock_agent, cli: Callable[..., None], tmp_path: Path, capsys
):
    """colin skills update reports failed updates."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    # Create a skill with a broken manifest (missing project_config)
    broken_skill = skills_dir / "broken-skill"
    broken_skill.mkdir()
    (broken_skill / ".colin-manifest.json").write_text(
        json.dumps({"files": {}})  # Missing project_config
    )

    # Create a working skill
    working_skill = skills_dir / "working-skill"
    cli("run", "--quiet", "--output", str(working_skill))

    # Run skills update - should fail due to broken skill
    try:
        cli("skills", "update", str(skills_dir))
    except SystemExit as e:
        assert e.code == 1

    captured = capsys.readouterr()
    assert "working-skill" in captured.out
    assert "broken-skill" in captured.out
    assert "1" in captured.out and "failed" in captured.out
