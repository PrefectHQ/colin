"""Global settings for Colin."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ColinSettings(BaseSettings):
    """Global Colin settings.

    These can be overridden via environment variables (uppercase, prefixed with COLIN_).
    """

    model_config = SettingsConfigDict(
        env_prefix="COLIN_",
        case_sensitive=False,
    )

    default_llm_model: str = Field(
        default="anthropic:claude-sonnet-4-5",
        description="Default LLM model (e.g., 'anthropic:claude-sonnet-4-5', 'openai:gpt-4o')",
    )

    manifest_file: str = Field(
        default="manifest.json",
        description="Name of the manifest file",
    )

    fernet_key: str | None = Field(
        default=None,
        description="Fernet encryption key for OAuth token storage.",
    )


# Global settings instance
settings = ColinSettings()
