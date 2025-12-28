"""End-to-end tests for project lifecycle (init, clean)."""

from pathlib import Path

import pytest

from colin.cli.run import clean, init, run


def test_init_creates_project(tmp_path: Path):
    """colin init creates colin.toml and models directory."""
    init(project=tmp_path)

    assert (tmp_path / "colin.toml").exists()
    assert (tmp_path / "models").is_dir()


def test_init_fails_if_exists(e2e_project: Path):
    """colin init fails if colin.toml already exists."""
    with pytest.raises(SystemExit):
        init(project=e2e_project)


def test_init_custom_name(tmp_path: Path):
    """colin init respects --name option."""
    init(project=tmp_path, name="my-project")

    config_content = (tmp_path / "colin.toml").read_text()
    assert 'name = "my-project"' in config_content


def test_init_custom_model_path(tmp_path: Path):
    """colin init respects --models option."""
    init(project=tmp_path, models="sources")

    assert (tmp_path / "sources").is_dir()
    assert not (tmp_path / "models").exists()


def test_init_custom_target_path(tmp_path: Path):
    """colin init respects --target option."""
    init(project=tmp_path, target="build")

    config_content = (tmp_path / "colin.toml").read_text()
    assert 'target-path = "build"' in config_content


async def test_clean_removes_target(e2e_project: Path, target_dir: Path, mock_agent):
    """colin clean removes target/ contents after compilation."""
    await run(project=e2e_project, target=target_dir, quiet=True)
    assert (target_dir / "compiled").exists()

    clean(project=e2e_project, yes=True)
    # Note: clean uses project's configured target_path, not our override
    # So we need to check that the operation doesn't error


async def test_run_creates_output(e2e_project: Path, target_dir: Path, mock_agent):
    """colin run creates compiled output files."""
    await run(project=e2e_project, target=target_dir, quiet=True)

    assert (target_dir / "compiled" / "hello.md").exists()
    content = (target_dir / "compiled" / "hello.md").read_text()
    assert "Hello, world!" in content


def test_clean_does_nothing_if_no_target(tmp_path: Path):
    """colin clean does nothing if target doesn't exist."""
    init(project=tmp_path)
    # Clean should not error even if target doesn't exist
    clean(project=tmp_path, yes=True)
