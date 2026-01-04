"""Tests for variable resolution."""

from datetime import date, datetime

import pytest
from pydantic import SecretStr

from colin.api.project import VarConfig


class TestVarConfigResolve:
    """Tests for VarConfig.resolve() method."""

    def test_cli_override_takes_precedence(self) -> None:
        """CLI vars override defaults."""
        config = VarConfig(type="string", default="dev")
        result = config.resolve("env", cli_value="prod")

        assert result == "prod"

    def test_default_used_when_no_cli(self) -> None:
        """Default is used when no CLI override."""
        config = VarConfig(type="string", default="dev")
        result = config.resolve("env")

        assert result == "dev"

    def test_optional_returns_none(self) -> None:
        """Optional var without default returns None."""
        config = VarConfig(type="string", optional=True)
        result = config.resolve("key")

        assert result is None

    def test_required_raises_error(self) -> None:
        """Required var without value raises error."""
        config = VarConfig(type="string")

        with pytest.raises(ValueError, match="Required variable 'key'"):
            config.resolve("key")

    def test_env_var_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Environment variable overrides default."""
        monkeypatch.setenv("COLIN_VAR_API_KEY", "sk-from-env")

        config = VarConfig(type="string", default="default-key")
        result = config.resolve("api_key")

        assert result == "sk-from-env"

    def test_cli_overrides_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CLI takes precedence over environment variable."""
        monkeypatch.setenv("COLIN_VAR_API_KEY", "sk-from-env")

        config = VarConfig(type="string", default="default-key")
        result = config.resolve("api_key", cli_value="sk-from-cli")

        assert result == "sk-from-cli"

    def test_env_var_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Environment variable name is uppercased."""
        monkeypatch.setenv("COLIN_VAR_MY_VAR", "value")

        config = VarConfig(type="string")
        result = config.resolve("my_var")

        assert result == "value"


class TestTypeConversion:
    """Tests for VarConfig type conversion."""

    def test_bool_conversion_true(self) -> None:
        """Bool type converts various truthy strings."""
        for value in ["true", "True", "TRUE", "1", "yes", "YES", "on", "ON"]:
            config = VarConfig(type="bool")
            result = config.resolve("flag", cli_value=value)
            assert result is True, f"Failed for value: {value}"

    def test_bool_conversion_false(self) -> None:
        """Bool type converts various falsy strings."""
        for value in ["false", "False", "FALSE", "0", "no", "NO", "off", "OFF"]:
            config = VarConfig(type="bool")
            result = config.resolve("flag", cli_value=value)
            assert result is False, f"Failed for value: {value}"

    def test_bool_conversion_invalid(self) -> None:
        """Bool type rejects invalid strings."""
        config = VarConfig(type="bool")

        with pytest.raises(ValueError, match="'flag'.*invalid bool"):
            config.resolve("flag", cli_value="maybe")

    def test_bool_native_value(self) -> None:
        """Bool type preserves native bool from TOML."""
        config = VarConfig(type="bool", default=True)
        result = config.resolve("flag")

        assert result is True

    def test_int_conversion(self) -> None:
        """Int type converts to integer."""
        config = VarConfig(type="int")
        result = config.resolve("count", cli_value="42")

        assert result == 42
        assert isinstance(result, int)

    def test_int_conversion_invalid(self) -> None:
        """Int type rejects non-numeric strings."""
        config = VarConfig(type="int")

        with pytest.raises(ValueError, match="'count'.*invalid int"):
            config.resolve("count", cli_value="abc")

    def test_float_conversion(self) -> None:
        """Float type converts to float."""
        config = VarConfig(type="float")
        result = config.resolve("rate", cli_value="3.14")

        assert result == 3.14
        assert isinstance(result, float)

    def test_date_conversion(self) -> None:
        """Date type converts to date object."""
        config = VarConfig(type="date")
        result = config.resolve("target", cli_value="2024-01-15")

        assert result == date(2024, 1, 15)
        assert isinstance(result, date)
        assert not isinstance(result, datetime)

    def test_date_conversion_invalid(self) -> None:
        """Date type rejects invalid date strings."""
        config = VarConfig(type="date")

        with pytest.raises(ValueError, match="'target'.*invalid date"):
            config.resolve("target", cli_value="not-a-date")

    def test_timestamp_conversion(self) -> None:
        """Timestamp type converts to datetime object."""
        config = VarConfig(type="timestamp")
        result = config.resolve("created", cli_value="2024-01-15T10:30:00")

        assert isinstance(result, datetime)
        assert result.year == 2024
        assert result.hour == 10

    def test_timestamp_conversion_invalid(self) -> None:
        """Timestamp type rejects invalid timestamp strings."""
        config = VarConfig(type="timestamp")

        with pytest.raises(ValueError, match="'created'.*invalid timestamp"):
            config.resolve("created", cli_value="not-a-timestamp")

    def test_secret_conversion(self) -> None:
        """Secret type returns SecretStr."""
        config = VarConfig(type="secret")
        result = config.resolve("api_key", cli_value="sk-1234")

        assert isinstance(result, SecretStr)
        assert result.get_secret_value() == "sk-1234"


class TestPrecedence:
    """Tests for variable precedence."""

    def test_full_precedence_chain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CLI > env var > default > optional."""
        monkeypatch.setenv("COLIN_VAR_VAR1", "from-env")

        # CLI > env > default
        var1 = VarConfig(type="string", default="default1")
        assert var1.resolve("var1", cli_value="from-cli") == "from-cli"

        # env > default (no CLI)
        var2 = VarConfig(type="string", default="default2")
        assert var2.resolve("var2") == "default2"  # No env var set for var2

        # default (no CLI, no env)
        var3 = VarConfig(type="string", default="default3")
        assert var3.resolve("var3") == "default3"

        # None (optional, no value)
        var4 = VarConfig(type="string", optional=True)
        assert var4.resolve("var4") is None
