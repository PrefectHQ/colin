"""Tests for colin run and clean commands."""

import json
from collections.abc import Callable
from pathlib import Path

from tests.cli.conftest import strip_ansi


def test_run_creates_output(
    test_project: Path, output_dir: Path, mock_agent, cli: Callable[..., None]
):
    """colin run creates compiled output files."""
    cli("run", "--output", str(output_dir), "--quiet")

    assert (output_dir / "greeting.md").exists()


def test_clean_removes_stale_files_from_output(
    test_project: Path, mock_agent, cli: Callable[..., None]
):
    """colin clean removes stale files from output/, keeps published outputs."""
    project_output = test_project / "output"

    # Run to create output
    cli("run", "--quiet")
    assert (project_output / "greeting.md").exists()

    # Add a stale file
    stale_file = project_output / "old_file.txt"
    stale_file.write_text("stale content")

    # Clean should remove only the stale file
    cli("clean", "--yes")
    assert not stale_file.exists(), "Stale file should be removed"
    assert (project_output / "greeting.md").exists(), "Published output should remain"


def test_clean_does_not_touch_cache(test_project: Path, mock_agent, cli: Callable[..., None]):
    """colin clean does not remove files from .colin/ (only output/)."""
    colin_dir = test_project / ".colin"
    compiled_dir = colin_dir / "compiled"

    # Run to create cache
    cli("run", "--quiet")
    assert compiled_dir.exists()
    assert (compiled_dir / "greeting.md").exists()

    # Add an extra file to compiled/
    extra_file = compiled_dir / "extra.md"
    extra_file.write_text("extra content")

    # Default clean should NOT touch .colin/ directory
    cli("clean", "--yes")
    assert extra_file.exists(), "Files in .colin/ should not be removed by default clean"
    assert (compiled_dir / "greeting.md").exists(), "Compiled output should remain"
    assert (colin_dir / "manifest.json").exists(), "Manifest should remain"


def test_clean_all_removes_stale_from_compiled(
    test_project: Path, mock_agent, cli: Callable[..., None]
):
    """colin clean --all removes stale files from both output/ and .colin/compiled/."""
    colin_dir = test_project / ".colin"
    compiled_dir = colin_dir / "compiled"
    project_output = test_project / "output"

    # Run to create output and cache
    cli("run", "--quiet")
    assert project_output.exists()
    assert compiled_dir.exists()
    assert (compiled_dir / "greeting.md").exists()

    # Add stale files to both locations
    stale_output = project_output / "stale_output.txt"
    stale_output.write_text("stale output")
    stale_compiled = compiled_dir / "stale_compiled.txt"
    stale_compiled.write_text("stale compiled")

    # Clean --all should remove stale files from both locations
    cli("clean", "--all", "--yes")
    assert not stale_output.exists(), "Stale file in output/ should be removed"
    assert not stale_compiled.exists(), "Stale file in .colin/compiled/ should be removed"
    assert (project_output / "greeting.md").exists(), "Tracked output should remain"
    assert (compiled_dir / "greeting.md").exists(), "Tracked compiled file should remain"
    assert (colin_dir / "manifest.json").exists(), "Manifest should remain"


def test_clean_nothing_to_clean(test_project: Path, mock_agent, cli: Callable[..., None]):
    """colin clean reports nothing to clean when no stale files exist."""
    # Run to create output
    cli("run", "--quiet")

    # Clean should report nothing to clean (no stale files)
    cli("clean", "--yes")  # Should not error, just report nothing to clean


def test_clean_does_nothing_if_no_output(tmp_path: Path, monkeypatch, cli: Callable[..., None]):
    """colin clean does nothing if output doesn't exist."""
    monkeypatch.chdir(tmp_path)

    cli("init")

    # Clean should not error even if output doesn't exist
    cli("clean", "--yes")


def test_run_warns_about_stale_files(
    test_project: Path, mock_agent, capsys, cli: Callable[..., None]
):
    """colin run warns about stale files in output/."""
    project_output = test_project / "output"

    # Run to create output
    cli("run", "--quiet")

    # Add a stale file
    stale_file = project_output / "stale.txt"
    stale_file.write_text("stale content")

    # Run again - should warn about stale file
    cli("run", "--quiet")

    captured = capsys.readouterr()
    output = strip_ansi(captured.err)
    assert "stale file" in output.lower()
    assert "colin clean" in output


def test_run_suggests_update_in_output_directory(
    test_project: Path, mock_agent, cli: Callable[..., None], monkeypatch, capsys, tmp_path
):
    """colin run suggests `colin update` when run in a standalone output directory."""
    # Create output in a separate location (not inside project)
    standalone_output = tmp_path / "standalone_output"
    standalone_output.mkdir()

    # Run to create output with manifest in the standalone location
    cli("run", "--quiet", "--output", str(standalone_output))

    # Change to standalone output directory (has manifest but no colin.toml anywhere up)
    monkeypatch.chdir(standalone_output)

    # Running `colin run` here should fail and suggest `colin update`
    try:
        cli("run")
    except SystemExit:
        pass  # Expected to fail

    captured = capsys.readouterr()
    # Rich console may output to stdout or stderr
    output = strip_ansi(captured.err + captured.out)
    assert "looks like an output directory" in output.lower()
    assert "colin update" in output


def test_update_suggests_run_in_source_project(
    test_project: Path, mock_agent, cli: Callable[..., None], capsys
):
    """colin update suggests `colin run` when run in a source project directory."""
    # Run update in a source project (has colin.toml but no manifest)
    try:
        cli("update")
    except SystemExit:
        pass  # Expected to fail (no manifest)

    captured = capsys.readouterr()
    # Rich console may output to stdout or stderr
    output = strip_ansi(captured.err + captured.out)
    assert "looks like a source project" in output.lower()
    assert "colin run" in output


async def test_provider_llm_model_config(
    tmp_path: Path, monkeypatch, mock_agent, cli: Callable[..., None]
):
    """[[providers.llm]] model configuration is respected and used in extract calls."""
    from unittest.mock import AsyncMock, patch

    import tomli
    import tomli_w

    from colin.api.project import ProjectConfig, load_project
    from colin.cli.run import init
    from colin.compiler.cache import set_compile_context
    from colin.compiler.context import CompileContext
    from colin.models import Manifest
    from colin.providers.llm import LLMProvider
    from colin.providers.manager import create_provider
    from colin.providers.project import ProjectProvider

    # Initialize project
    init(project=tmp_path)
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
    config = ProjectConfig(
        name="test",
        project_root=tmp_path,
        model_path=tmp_path / "models",
        output_path=tmp_path / "output",
        manifest_path=tmp_path / ".colin" / "manifest.json",
    )
    compile_ctx = CompileContext(
        manifest=Manifest(),
        document_uri="project://test.md",
        project_provider=project_provider,
        config=config,
    )

    # Mock infer_model to return test model for "openai:gpt-4o" to avoid API key requirement
    # but with model_name set to "gpt-4o" so the test assertion passes
    from pydantic_ai.models import Model
    from pydantic_ai.models import infer_model as original_infer_model

    def mock_infer_model(model: str | object) -> Model:
        if model == "openai:gpt-4o":
            # Return test model wrapped with correct model_name
            # This ensures the model config is actually used (not just stored)
            test_model = original_infer_model("test")

            # Create a wrapper class that delegates to test_model but has correct model_name
            class ModelWrapper:
                """Wrapper that uses test model but reports correct model_name."""

                def __init__(self, wrapped: Model, name: str) -> None:
                    self._wrapped = wrapped
                    self._model_name = name

                @property
                def model_name(self) -> str:
                    return self._model_name

                def __getattr__(self, name: str) -> object:
                    # Delegate all other attributes/methods to wrapped test model
                    return getattr(self._wrapped, name)

            return ModelWrapper(test_model, "gpt-4o")  # type: ignore[return-value]
        # Type cast needed because model could be object, but we know it's valid for infer_model
        return original_infer_model(model)  # type: ignore[arg-type]

    mock_result = AsyncMock()
    mock_result.output = "extracted content"

    set_compile_context(compile_ctx)
    try:
        with (
            patch("colin.providers.llm.infer_model", side_effect=mock_infer_model),
            patch("colin.providers.llm.Agent.run", return_value=mock_result),
        ):
            await provider._extract("test content", "extract this")

        # Verify the LLM call was recorded with the correct model
        # Note: infer_model strips the provider prefix, so "openai:gpt-4o" -> "gpt-4o"
        assert len(compile_ctx.llm_calls) == 1
        llm_call = list(compile_ctx.llm_calls.values())[0]
        assert llm_call.model == "gpt-4o"
    finally:
        set_compile_context(None)


def test_update_from_output_directory(
    test_project: Path, mock_agent, cli: Callable[..., None], monkeypatch
):
    """colin update updates outputs from their source project."""
    project_output = test_project / "output"

    # First run to create output with manifest
    cli("run", "--quiet")
    assert (project_output / "greeting.md").exists()

    # Verify manifest has project_config
    manifest_path = project_output / ".colin-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert "project_config" in manifest
    assert manifest["project_config"].endswith("colin.toml")

    # Change to output directory and run update
    monkeypatch.chdir(project_output)
    cli("update", "--quiet")

    # Should still have output
    assert (project_output / "greeting.md").exists()


def test_update_errors_without_manifest(
    tmp_path: Path, cli: Callable[..., None], monkeypatch, capsys
):
    """colin update errors in directory without manifest."""
    monkeypatch.chdir(tmp_path)

    try:
        cli("update")
    except SystemExit as e:
        assert e.code == 1

    captured = capsys.readouterr()
    output = strip_ansi(captured.err)
    assert ".colin-manifest.json" in output


def test_update_errors_with_invalid_json(
    tmp_path: Path, cli: Callable[..., None], monkeypatch, capsys
):
    """colin update errors gracefully on invalid JSON manifest."""
    monkeypatch.chdir(tmp_path)

    # Create an invalid JSON manifest
    manifest_path = tmp_path / ".colin-manifest.json"
    manifest_path.write_text("{ invalid json }")

    try:
        cli("update")
    except SystemExit as e:
        assert e.code == 1

    captured = capsys.readouterr()
    output = strip_ansi(captured.err)
    assert "Invalid JSON" in output


def test_update_uses_stored_vars(
    test_project: Path, mock_agent, cli: Callable[..., None], monkeypatch
):
    """colin update uses vars stored in manifest."""
    project_output = test_project / "output"

    # Run with a var
    cli("run", "--quiet", "--var", "test_var=original_value")

    # Check manifest stored the var
    manifest_path = project_output / ".colin-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest.get("vars", {}).get("test_var") == "original_value"

    # Change to output and run update (should use stored vars)
    monkeypatch.chdir(project_output)
    cli("update", "--quiet")

    # Manifest should still have the var
    manifest = json.loads(manifest_path.read_text())
    assert manifest.get("vars", {}).get("test_var") == "original_value"


def test_update_cli_vars_override_stored(
    test_project: Path, mock_agent, cli: Callable[..., None], monkeypatch
):
    """colin update --var overrides stored vars."""
    project_output = test_project / "output"

    # Run with a var
    cli("run", "--quiet", "--var", "test_var=original_value")

    # Change to output and run update with override
    monkeypatch.chdir(project_output)
    cli("update", "--quiet", "--var", "test_var=new_value")

    # Manifest should have the new value
    manifest_path = project_output / ".colin-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest.get("vars", {}).get("test_var") == "new_value"
