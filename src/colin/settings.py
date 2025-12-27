"""Global settings for Colin."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ColinSettings(BaseSettings):
    """Global Colin settings.

    These can be overridden via environment variables (uppercase, prefixed with COLIN_).
    For example: COLIN_DEFAULT_LLM_PROVIDER=openai
    """

    model_config = SettingsConfigDict(
        env_prefix="COLIN_",
        case_sensitive=False,
    )

    default_llm_provider: str = Field(
        default="stub",
        description="Default LLM provider to use (e.g., 'stub', 'openai', 'anthropic')",
    )

    manifest_file: str = Field(
        default="manifest.json",
        description="Name of the manifest file",
    )


# Global settings instance
settings = ColinSettings()

