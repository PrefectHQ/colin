"""Tests for colin init command."""

from collections.abc import Callable
from pathlib import Path

import pytest

from colin.cli import app


def test_init_creates_project(tmp_path: Path, monkeypatch, cli: Callable[..., None]):
    """colin init creates colin.toml and models directory."""
    monkeypatch.chdir(tmp_path)

    cli("init")

    assert (tmp_path / "colin.toml").exists()
    assert (tmp_path / "models").is_dir()


def test_init_fails_if_exists(tmp_path: Path, monkeypatch, cli: Callable[..., None]):
    """colin init fails if colin.toml already exists."""
    monkeypatch.chdir(tmp_path)
    cli("init")

    with pytest.raises(SystemExit) as exc_info:
        app(["init"])

    assert exc_info.value.code == 1


def test_init_custom_name(tmp_path: Path, monkeypatch, cli: Callable[..., None]):
    """colin init respects --name option."""
    monkeypatch.chdir(tmp_path)

    cli("init", "--name", "my-project")

    config_content = (tmp_path / "colin.toml").read_text()
    assert 'name = "my-project"' in config_content


def test_init_custom_model_path(tmp_path: Path, monkeypatch, cli: Callable[..., None]):
    """colin init respects --models option."""
    monkeypatch.chdir(tmp_path)

    cli("init", "--models", "sources")

    config_content = (tmp_path / "colin.toml").read_text()
    assert 'model-path = "sources"' in config_content


def test_init_custom_output_path(tmp_path: Path, monkeypatch, cli: Callable[..., None]):
    """colin init respects --output option."""
    monkeypatch.chdir(tmp_path)

    cli("init", "--output", "build")

    config_content = (tmp_path / "colin.toml").read_text()
    assert 'output-path = "build"' in config_content


def test_init_blank_template(tmp_path: Path, monkeypatch, cli: Callable[..., None]):
    """colin init --template blank creates only colin.toml."""
    monkeypatch.chdir(tmp_path)

    cli("init", "--template", "blank")

    assert (tmp_path / "colin.toml").exists()
    # blank template has no models directory
    assert not (tmp_path / "models").exists()


def test_init_quickstart_template(tmp_path: Path, monkeypatch, cli: Callable[..., None]):
    """colin init --template quickstart creates project with model files."""
    monkeypatch.chdir(tmp_path)

    cli("init", "--template", "quickstart", "--no-interactive")

    assert (tmp_path / "colin.toml").exists()
    assert (tmp_path / "models").is_dir()
    assert (tmp_path / "models" / "welcome.md").exists()
    assert (tmp_path / "models" / "project-info.md").exists()


def test_init_creates_new_directory(tmp_path: Path, monkeypatch, cli: Callable[..., None]):
    """colin init creates project in a new subdirectory."""
    monkeypatch.chdir(tmp_path)

    cli("init", "my-project")

    project_dir = tmp_path / "my-project"
    assert project_dir.is_dir()
    assert (project_dir / "colin.toml").exists()
    assert (project_dir / "models").is_dir()


def test_init_custom_template_path(tmp_path: Path, monkeypatch, cli: Callable[..., None]):
    """colin init supports custom template directories."""
    # Create a custom template
    template_dir = tmp_path / "my-template"
    template_dir.mkdir()
    (template_dir / "colin.toml").write_text('[project]\nname = "{{ project_name }}"\n')
    (template_dir / "models").mkdir()
    (template_dir / "models" / "hello.md").write_text("# Hello\n")

    project_dir = tmp_path / "my-project"
    monkeypatch.chdir(tmp_path)

    cli("init", "my-project", "--template", str(template_dir))

    assert (project_dir / "colin.toml").exists()
    assert (project_dir / "models" / "hello.md").exists()
    # Check variable substitution in colin.toml
    content = (project_dir / "colin.toml").read_text()
    assert 'name = "my-project"' in content


def test_init_invalid_template_fails(tmp_path: Path, monkeypatch):
    """colin init fails with invalid template name."""
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        app(["init", "--template", "nonexistent"])

    assert exc_info.value.code == 1
