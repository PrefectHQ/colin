"""Tests for colin init command."""

from collections.abc import Callable
from pathlib import Path

import pytest


def test_init_creates_project(tmp_path: Path, monkeypatch, cli: Callable[..., None]):
    """colin init creates colin.toml and models directory."""
    monkeypatch.chdir(tmp_path)

    cli("init")

    assert (tmp_path / "colin.toml").exists()
    assert (tmp_path / "models").is_dir()
    assert (tmp_path / "models" / "hello.md").exists()


def test_init_fails_if_exists(tmp_path: Path, monkeypatch, cli: Callable[..., None]):
    """colin init fails if colin.toml already exists."""
    monkeypatch.chdir(tmp_path)
    cli("init")

    with pytest.raises(SystemExit) as exc_info:
        cli("init")

    assert exc_info.value.code == 1


def test_init_custom_name(tmp_path: Path, monkeypatch, cli: Callable[..., None]):
    """colin init respects --name option."""
    monkeypatch.chdir(tmp_path)

    cli("init", "--name", "my-project")

    config_content = (tmp_path / "colin.toml").read_text()
    assert 'name = "my-project"' in config_content


def test_init_creates_new_directory(tmp_path: Path, monkeypatch, cli: Callable[..., None]):
    """colin init creates project in a new subdirectory."""
    monkeypatch.chdir(tmp_path)

    cli("init", "my-project")

    project_dir = tmp_path / "my-project"
    assert project_dir.is_dir()
    assert (project_dir / "colin.toml").exists()
    assert (project_dir / "models").is_dir()
    assert (project_dir / "models" / "hello.md").exists()


def test_init_uses_directory_name_as_project_name(
    tmp_path: Path, monkeypatch, cli: Callable[..., None]
):
    """colin init uses directory name as project name by default."""
    monkeypatch.chdir(tmp_path)

    cli("init", "my-awesome-project")

    config_content = (tmp_path / "my-awesome-project" / "colin.toml").read_text()
    assert 'name = "my-awesome-project"' in config_content


def test_init_custom_models_dir(tmp_path: Path, monkeypatch, cli: Callable[..., None]):
    """colin init respects --models option."""
    monkeypatch.chdir(tmp_path)

    cli("init", "--models", "src/docs")

    assert (tmp_path / "src/docs").is_dir()
    assert (tmp_path / "src/docs" / "hello.md").exists()
    config_content = (tmp_path / "colin.toml").read_text()
    assert 'models = "src/docs"' in config_content


def test_init_custom_output_dir(tmp_path: Path, monkeypatch, cli: Callable[..., None]):
    """colin init respects --output option."""
    monkeypatch.chdir(tmp_path)

    cli("init", "--output", "dist")

    config_content = (tmp_path / "colin.toml").read_text()
    assert 'output = "dist"' in config_content


def test_init_default_dirs_not_in_config(tmp_path: Path, monkeypatch, cli: Callable[..., None]):
    """colin init doesn't write default models/output to config."""
    monkeypatch.chdir(tmp_path)

    cli("init")

    config_content = (tmp_path / "colin.toml").read_text()
    assert "models" not in config_content
    assert "output" not in config_content
