"""Tests for colin run and clean commands."""

from collections.abc import Callable
from pathlib import Path

from tests.cli.conftest import strip_ansi


def test_run_creates_output(
    test_project: Path, target_dir: Path, mock_agent, cli: Callable[..., None]
):
    """colin run creates compiled output files."""
    cli("run", "--target", str(target_dir), "--quiet")

    assert (target_dir / "greeting.md").exists()


def test_clean_removes_target(test_project: Path, mock_agent, cli: Callable[..., None]):
    """colin clean removes target/ contents after compilation."""
    project_target = test_project / "target"

    # Run to create output
    cli("run", "--quiet")
    assert (project_target).exists()

    # Clean
    cli("clean", "--yes")
    assert not (project_target).exists()


def test_clean_does_nothing_if_no_target(tmp_path: Path, monkeypatch, cli: Callable[..., None]):
    """colin clean does nothing if target doesn't exist."""
    monkeypatch.chdir(tmp_path)

    cli("init")

    # Clean should not error even if target doesn't exist
    cli("clean", "--yes")


def test_dry_run_shows_correct_uri(test_project: Path, capsys, cli: Callable[..., None]):
    """colin run --dry-run shows URIs without double .md extension."""
    cli("run", "--dry-run")

    captured = capsys.readouterr()
    output = strip_ansi(captured.out)
    # Should show project://greeting.md, not project://greeting.md.md
    assert "project://greeting.md.md" not in output
    assert "project://greeting.md" in output


async def test_provider_llm_model_config(
    tmp_path: Path, monkeypatch, mock_agent, cli: Callable[..., None]
):
    """[[providers.llm]] model configuration is respected and used in extract calls."""
    from unittest.mock import AsyncMock, patch

    import tomli
    import tomli_w

    from colin.api.project import load_project
    from colin.compiler.context import CompileContext
    from colin.models import Manifest
    from colin.providers.cache import set_compile_context
    from colin.providers.llm import LLMProvider
    from colin.providers.manager import create_provider
    from colin.providers.project import ProjectProvider

    # Initialize project
    cli("init", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    # Add [[providers.llm]] model config to colin.toml
    config_path = tmp_path / "colin.toml"
    with open(config_path, "rb") as f:
        config = tomli.load(f)

    config["providers"] = {"llm": [{"model": "openai:gpt-4o"}]}

    with open(config_path, "wb") as f:
        tomli_w.dump(config, f)

    # Load project and verify provider configuration
    project = load_project(config_path)
    llm_config = project.providers.get("llm")
    assert llm_config is not None
    assert llm_config.provider_type == "llm"
    assert llm_config.config["model"] == "openai:gpt-4o"

    # Verify the provider is instantiated with the correct model
    provider = create_provider(llm_config)
    assert isinstance(provider, LLMProvider)
    assert provider.model == "openai:gpt-4o"

    # Verify the model is actually used when calling extract
    project_provider = ProjectProvider(base_path=tmp_path)
    compile_ctx = CompileContext(
        manifest=Manifest(),
        document_uri="project://test.md",
        project_provider=project_provider,
    )

    # Mock Agent.run to avoid actual LLM call
    mock_result = AsyncMock()
    mock_result.output = "extracted content"

    set_compile_context(compile_ctx)
    try:
        with patch("colin.providers.llm.Agent.run", return_value=mock_result):
            await provider._extract("test content", "extract this")

        # Verify the LLM call was recorded with the correct model
        # Note: infer_model strips the provider prefix, so "openai:gpt-4o" -> "gpt-4o"
        assert len(compile_ctx.llm_calls) == 1
        llm_call = list(compile_ctx.llm_calls.values())[0]
        assert llm_call.model == "gpt-4o"
    finally:
        set_compile_context(None)
