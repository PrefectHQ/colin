"""Tests for variable resolution."""

from datetime import date, datetime

import pytest

from colin.api.project import VarConfig
from colin.providers.variable import VariableProvider


def make_provider(
    name: str, config: VarConfig, cli_vars: dict[str, str] | None = None
) -> VariableProvider:
    """Create a VariableProvider with a single variable config."""
    return VariableProvider(var_configs={name: config}, cli_vars=cli_vars or {})


class TestVariableProviderResolve:
    """Tests for VariableProvider.get() method."""

    def test_cli_override_takes_precedence(self) -> None:
        """CLI vars override defaults."""
        provider = make_provider("env", VarConfig(type="string", default="dev"), {"env": "prod"})
        result = provider.get("env")

        assert result == "prod"

    def test_default_used_when_no_cli(self) -> None:
        """Default is used when no CLI override."""
        provider = make_provider("env", VarConfig(type="string", default="dev"))
        result = provider.get("env")

        assert result == "dev"

    def test_optional_returns_none(self) -> None:
        """Optional var without default returns None."""
        provider = make_provider("key", VarConfig(type="string", optional=True))
        result = provider.get("key")

        assert result is None

    def test_required_raises_error(self) -> None:
        """Required var without value raises error."""
        provider = make_provider("key", VarConfig(type="string"))

        with pytest.raises(ValueError, match="Required variable 'key'"):
            provider.get("key")

    def test_env_var_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Environment variable overrides default."""
        monkeypatch.setenv("COLIN_VAR_API_KEY", "sk-from-env")

        provider = make_provider("api_key", VarConfig(type="string", default="default-key"))
        result = provider.get("api_key")

        assert result == "sk-from-env"

    def test_cli_overrides_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CLI takes precedence over environment variable."""
        monkeypatch.setenv("COLIN_VAR_API_KEY", "sk-from-env")

        provider = make_provider(
            "api_key", VarConfig(type="string", default="default-key"), {"api_key": "sk-from-cli"}
        )
        result = provider.get("api_key")

        assert result == "sk-from-cli"

    def test_env_var_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Environment variable name is uppercased."""
        monkeypatch.setenv("COLIN_VAR_MY_VAR", "value")

        provider = make_provider("my_var", VarConfig(type="string"))
        result = provider.get("my_var")

        assert result == "value"


class TestTypeConversion:
    """Tests for VariableProvider type conversion."""

    def test_bool_conversion_true(self) -> None:
        """Bool type converts various truthy strings."""
        for value in ["true", "True", "TRUE", "1", "yes", "YES", "on", "ON"]:
            provider = make_provider("flag", VarConfig(type="bool"), {"flag": value})
            result = provider.get("flag")
            assert result is True, f"Failed for value: {value}"

    def test_bool_conversion_false(self) -> None:
        """Bool type converts various falsy strings."""
        for value in ["false", "False", "FALSE", "0", "no", "NO", "off", "OFF"]:
            provider = make_provider("flag", VarConfig(type="bool"), {"flag": value})
            result = provider.get("flag")
            assert result is False, f"Failed for value: {value}"

    def test_bool_conversion_invalid(self) -> None:
        """Bool type rejects invalid strings."""
        provider = make_provider("flag", VarConfig(type="bool"), {"flag": "maybe"})

        with pytest.raises(ValueError, match="'flag'.*invalid bool"):
            provider.get("flag")

    def test_bool_native_value(self) -> None:
        """Bool type preserves native bool from TOML."""
        provider = make_provider("flag", VarConfig(type="bool", default=True))
        result = provider.get("flag")

        assert result is True

    def test_int_conversion(self) -> None:
        """Int type converts to integer."""
        provider = make_provider("count", VarConfig(type="int"), {"count": "42"})
        result = provider.get("count")

        assert result == 42
        assert isinstance(result, int)

    def test_int_conversion_invalid(self) -> None:
        """Int type rejects non-numeric strings."""
        provider = make_provider("count", VarConfig(type="int"), {"count": "abc"})

        with pytest.raises(ValueError, match="'count'.*invalid int"):
            provider.get("count")

    def test_float_conversion(self) -> None:
        """Float type converts to float."""
        provider = make_provider("rate", VarConfig(type="float"), {"rate": "3.14"})
        result = provider.get("rate")

        assert result == 3.14
        assert isinstance(result, float)

    def test_date_conversion(self) -> None:
        """Date type converts to date object."""
        provider = make_provider("target", VarConfig(type="date"), {"target": "2024-01-15"})
        result = provider.get("target")

        assert result == date(2024, 1, 15)
        assert isinstance(result, date)
        assert not isinstance(result, datetime)

    def test_date_conversion_invalid(self) -> None:
        """Date type rejects invalid date strings."""
        provider = make_provider("target", VarConfig(type="date"), {"target": "not-a-date"})

        with pytest.raises(ValueError, match="'target'.*invalid date"):
            provider.get("target")

    def test_timestamp_conversion(self) -> None:
        """Timestamp type converts to datetime object."""
        provider = make_provider(
            "created", VarConfig(type="timestamp"), {"created": "2024-01-15T10:30:00"}
        )
        result = provider.get("created")

        assert isinstance(result, datetime)
        assert result.year == 2024
        assert result.hour == 10

    def test_timestamp_conversion_invalid(self) -> None:
        """Timestamp type rejects invalid timestamp strings."""
        provider = make_provider(
            "created", VarConfig(type="timestamp"), {"created": "not-a-timestamp"}
        )

        with pytest.raises(ValueError, match="'created'.*invalid timestamp"):
            provider.get("created")


class TestPrecedence:
    """Tests for variable precedence."""

    def test_full_precedence_chain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CLI > env var > default > optional."""
        monkeypatch.setenv("COLIN_VAR_VAR1", "from-env")

        # CLI > env > default
        provider1 = VariableProvider(
            var_configs={"var1": VarConfig(type="string", default="default1")},
            cli_vars={"var1": "from-cli"},
        )
        assert provider1.get("var1") == "from-cli"

        # env > default (no CLI)
        provider2 = VariableProvider(
            var_configs={"var2": VarConfig(type="string", default="default2")},
            cli_vars={},
        )
        assert provider2.get("var2") == "default2"  # No env var set for var2

        # default (no CLI, no env)
        provider3 = VariableProvider(
            var_configs={"var3": VarConfig(type="string", default="default3")},
            cli_vars={},
        )
        assert provider3.get("var3") == "default3"

        # None (optional, no value)
        provider4 = VariableProvider(
            var_configs={"var4": VarConfig(type="string", optional=True)},
            cli_vars={},
        )
        assert provider4.get("var4") is None
