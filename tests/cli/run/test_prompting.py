"""Tests for variable prompting in CLI."""

from pathlib import Path
from unittest.mock import patch

import pytest

from colin.api.project import ProjectConfig, VarConfig
from colin.cli.run import prompt_for_missing_vars


def make_config(vars_config: dict[str, dict]) -> ProjectConfig:
    """Create a minimal ProjectConfig with given vars."""
    return ProjectConfig(
        name="test",
        project_root=Path("/tmp/test"),
        model_path=Path("/tmp/test/models"),
        output_path=Path("/tmp/test/output"),
        manifest_path=Path("/tmp/test/.colin/manifest.json"),
        vars={name: VarConfig(**cfg) for name, cfg in vars_config.items()},
    )


class TestPromptForMissingVars:
    """Tests for prompt_for_missing_vars function."""

    def test_cli_value_takes_precedence(self) -> None:
        """Variables provided via CLI are not prompted."""
        config = make_config({"name": {"prompt": "Enter name:"}})

        with patch("colin.cli.run.Prompt.ask") as mock_ask:
            result = prompt_for_missing_vars(
                config,
                {"name": "from-cli"},
                interactive=True,
            )

        assert result == {"name": "from-cli"}
        mock_ask.assert_not_called()

    def test_env_value_takes_precedence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Variables provided via environment are not prompted."""
        monkeypatch.setenv("COLIN_VAR_NAME", "from-env")
        config = make_config({"name": {"prompt": "Enter name:"}})

        with patch("colin.cli.run.Prompt.ask") as mock_ask:
            result = prompt_for_missing_vars(
                config,
                {},
                interactive=True,
            )

        assert result == {}  # Not added because env var exists
        mock_ask.assert_not_called()

    def test_prompts_when_interactive(self) -> None:
        """Prompts for value when interactive and no value provided."""
        config = make_config({"name": {"prompt": "Enter name:"}})

        with patch("colin.cli.run.Prompt.ask", return_value="user-input") as mock_ask:
            result = prompt_for_missing_vars(
                config,
                {},
                interactive=True,
            )

        assert result == {"name": "user-input"}
        mock_ask.assert_called_once()
        # Check prompt contains prompt text
        call_args = mock_ask.call_args
        assert "Enter name:" in call_args.args[0]

    def test_uses_default_in_prompt(self) -> None:
        """Default value is passed to Prompt.ask."""
        config = make_config({"name": {"prompt": "Enter name:", "default": "default-val"}})

        with patch("colin.cli.run.Prompt.ask", return_value="default-val") as mock_ask:
            result = prompt_for_missing_vars(
                config,
                {},
                interactive=True,
            )

        assert result == {"name": "default-val"}
        # Check default was passed to Prompt.ask
        call_kwargs = mock_ask.call_args.kwargs
        assert call_kwargs.get("default") == "default-val"

    def test_skips_prompting_when_non_interactive(self) -> None:
        """Does not prompt when non-interactive (lets VariableProvider handle it)."""
        config = make_config({"name": {"prompt": "Enter name:", "default": "default-val"}})

        with patch("colin.cli.run.Prompt.ask") as mock_ask:
            result = prompt_for_missing_vars(
                config,
                {},
                interactive=False,
            )

        assert result == {}  # Not added; VariableProvider will use default
        mock_ask.assert_not_called()

    def test_skips_when_no_value_non_interactive(self) -> None:
        """Does not error when required variable missing in non-interactive mode."""
        # VariableProvider will error later if needed
        config = make_config({"name": {"prompt": "Enter name:"}})

        with patch("colin.cli.run.Prompt.ask") as mock_ask:
            result = prompt_for_missing_vars(
                config,
                {},
                interactive=False,
            )

        assert result == {}
        mock_ask.assert_not_called()

    def test_empty_input_not_added(self) -> None:
        """Empty input (None from Prompt.ask) is not added to result."""
        config = make_config({"name": {"prompt": "Enter name:"}})

        with patch("colin.cli.run.Prompt.ask", return_value=None):
            result = prompt_for_missing_vars(
                config,
                {},
                interactive=True,
            )

        assert result == {}  # Empty value not added

    def test_no_prompt_field_means_no_prompting(self) -> None:
        """Variables without prompt field are not prompted."""
        config = make_config({"name": {"type": "string"}})

        with patch("colin.cli.run.Prompt.ask") as mock_ask:
            result = prompt_for_missing_vars(
                config,
                {},
                interactive=True,
            )

        assert result == {}
        mock_ask.assert_not_called()

    def test_default_without_prompt_not_prompted(self) -> None:
        """Variables with default but no prompt are not prompted."""
        config = make_config({"name": {"default": "default-val"}})

        with patch("colin.cli.run.Prompt.ask") as mock_ask:
            result = prompt_for_missing_vars(
                config,
                {},
                interactive=True,
            )

        assert result == {}
        mock_ask.assert_not_called()

    def test_prompts_in_definition_order(self) -> None:
        """Variables are prompted in the order defined in config."""
        config = make_config(
            {
                "first": {"prompt": "First:"},
                "second": {"prompt": "Second:"},
                "third": {"prompt": "Third:"},
            }
        )

        with patch("colin.cli.run.Prompt.ask", side_effect=["a", "b", "c"]) as mock_ask:
            result = prompt_for_missing_vars(
                config,
                {},
                interactive=True,
            )

        assert result == {"first": "a", "second": "b", "third": "c"}
        assert mock_ask.call_count == 3
        # Check prompts contain expected prompt text in order
        calls = [call.args[0] for call in mock_ask.call_args_list]
        assert "First:" in calls[0]
        assert "Second:" in calls[1]
        assert "Third:" in calls[2]
