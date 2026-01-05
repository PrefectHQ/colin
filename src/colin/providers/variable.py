"""Variable provider for project variables with ref tracking."""

from __future__ import annotations

import hashlib
import os
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, ClassVar

from colin.api.project import VarConfig
from colin.providers.base import Provider

if TYPE_CHECKING:
    from colin.models import Ref


def _hash_value(value: Any) -> str:
    """Hash a variable value for version tracking."""
    return hashlib.sha256(str(value).encode()).hexdigest()[:16]


class VariableProvider(Provider):
    """Provider for project variables.

    Resolves variables from CLI args, environment variables, and defaults.
    Supports ref tracking for per-variable staleness detection.
    """

    namespace: ClassVar[str] = "variable"
    """Provider namespace for registration."""

    var_configs: dict[str, VarConfig]
    """Variable configurations from colin.toml."""

    cli_vars: dict[str, str]
    """CLI-provided variable overrides (--var key=value)."""

    _resolved: dict[str, Any] = {}
    """Cache of resolved variable values."""

    def get(self, name: str) -> Any:
        """Resolve and return a variable value.

        Values are cached after first resolution.

        Args:
            name: Variable name.

        Returns:
            Typed variable value.

        Raises:
            KeyError: If variable is not defined.
            ValueError: If required variable not provided or type conversion fails.
        """
        if name not in self._resolved:
            config = self.var_configs.get(name)
            if config is None:
                raise KeyError(f"Unknown variable: {name}")
            self._resolved[name] = self._resolve(name, config)
        return self._resolved[name]

    def _resolve(self, name: str, config: VarConfig) -> Any:
        """Resolve a variable's value.

        Precedence: CLI → env var → default → optional(None) → error
        """
        raw = self._load_raw(name, config)
        return self._convert(name, config, raw)

    def _load_raw(self, name: str, config: VarConfig) -> str | bool | int | float | None:
        """Load raw value from sources in precedence order."""
        # CLI override (highest priority)
        cli_value = self.cli_vars.get(name)
        if cli_value is not None:
            return cli_value

        # Environment variable
        env_name = f"COLIN_VAR_{name.upper()}"
        if (env_val := os.environ.get(env_name)) is not None:
            return env_val

        # Default from config
        if config.default is not None:
            return config.default

        # Optional returns None
        if config.optional:
            return None

        # Required but missing
        raise ValueError(
            f"Required variable '{name}' not provided. "
            f"Set via --var {name}=value, {env_name}=value, "
            f"or add a default in colin.toml"
        )

    def _convert(
        self, name: str, config: VarConfig, raw: str | bool | int | float | None
    ) -> str | bool | int | float | date | datetime | None:
        """Convert raw value to typed value."""
        if raw is None:
            return None

        try:
            match config.type:
                case "string":
                    return str(raw)
                case "bool":
                    if isinstance(raw, bool):
                        return raw
                    lower = str(raw).lower()
                    if lower in ("true", "1", "yes", "on"):
                        return True
                    if lower in ("false", "0", "no", "off"):
                        return False
                    raise ValueError(f"Use true/false, yes/no, 1/0, or on/off (got '{raw}')")
                case "int":
                    return int(raw)
                case "float":
                    return float(raw)
                case "date":
                    if isinstance(raw, date) and not isinstance(raw, datetime):
                        return raw
                    if isinstance(raw, datetime):
                        return raw.date()
                    return datetime.fromisoformat(str(raw)).date()
                case "timestamp":
                    if isinstance(raw, datetime):
                        return raw
                    return datetime.fromisoformat(str(raw))
                case _:
                    raise ValueError(f"unknown type '{config.type}'")
        except Exception as e:
            raise ValueError(f"Variable '{name}' has invalid {config.type} value: {e}") from e

    async def get_ref_version(self, ref: Ref) -> str:
        """Get current version hash for a variable ref.

        Used for staleness detection - if hash differs from
        stored hash, the document is stale.

        Args:
            ref: Ref with args["name"] containing variable name.

        Returns:
            Hash of current value (not the value itself).
        """
        name = ref.args["name"]
        value = self.get(name)
        return _hash_value(value)
