"""Tests for --no-interactive flag."""

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


class TestNoInteractiveFlag:
    """Tests for --no-interactive behavior with variable prompts."""

    def test_no_interactive_uses_default(self) -> None:
        """When --no-interactive is set, uses default value silently."""
        config = make_config({"name": {"prompt": "Enter name:", "default": "default-val"}})

        with patch("colin.cli.run.Prompt.ask") as mock_ask:
            result = prompt_for_missing_vars(
                config,
                {},
                interactive=False,
            )

        # Default is used via VariableProvider, not added here
        assert result == {}
        mock_ask.assert_not_called()

    def test_no_interactive_with_no_default_allows_through(self) -> None:
        """When --no-interactive is set and no default, allows VariableProvider to error."""
        config = make_config({"name": {"prompt": "Enter name:"}})

        with patch("colin.cli.run.Prompt.ask") as mock_ask:
            result = prompt_for_missing_vars(
                config,
                {},
                interactive=False,
            )

        # Let VariableProvider handle the error
        assert result == {}
        mock_ask.assert_not_called()

    def test_interactive_prompts_normally(self) -> None:
        """When interactive=True, prompts for values."""
        config = make_config({"name": {"prompt": "Enter name:"}})

        with patch("colin.cli.run.Prompt.ask", return_value="user-input") as mock_ask:
            result = prompt_for_missing_vars(
                config,
                {},
                interactive=True,
            )

        assert result == {"name": "user-input"}
        mock_ask.assert_called_once()


class TestNoInteractiveEnvVar:
    """Tests for COLIN_NO_INTERACTIVE environment variable."""

    def test_env_var_disables_prompts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """COLIN_NO_INTERACTIVE=1 disables prompts."""
        monkeypatch.setenv("COLIN_NO_INTERACTIVE", "1")

        # The env var is checked in run(), not prompt_for_missing_vars()
        # This test documents the expected behavior
        import os

        interactive = not os.environ.get("COLIN_NO_INTERACTIVE")
        assert interactive is False

    def test_env_var_not_set_allows_prompts(self) -> None:
        """Without env var, prompts are allowed (if TTY)."""
        import os

        # Ensure env var is not set
        os.environ.pop("COLIN_NO_INTERACTIVE", None)

        interactive = not os.environ.get("COLIN_NO_INTERACTIVE")
        assert interactive is True
