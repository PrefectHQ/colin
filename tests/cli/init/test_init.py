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

    assert (tmp_path / "sources").is_dir()
    assert not (tmp_path / "models").exists()


def test_init_custom_target_path(tmp_path: Path, monkeypatch, cli: Callable[..., None]):
    """colin init respects --target option."""
    monkeypatch.chdir(tmp_path)

    cli("init", "--target", "build")

    config_content = (tmp_path / "colin.toml").read_text()
    assert 'target-path = "build"' in config_content
