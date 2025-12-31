"""LLM provider functions for templates."""

from collections.abc import Awaitable, Callable
from typing import Any

from typing_extensions import Self

from colin.compiler.extensions.filters import _serialize_for_llm
from colin.models import RefResult
from colin.providers.base import Provider
from colin.providers.context import ProviderContext


class LLMProvider(Provider):
    """Provider wrapper for LLM template functions."""

    schemes: list[str] = ["llm"]

    @classmethod
    def from_config(cls, name: str | None, config: dict[str, Any]) -> Self:
        """Create LLM provider from configuration."""
        return cls()

    async def read(self, uri: str) -> str:
        raise ValueError("LLM provider does not support read()")

    def get_functions(self) -> dict[str, Callable[..., Awaitable[object]]]:
        return {
            "extract": self._extract,
            "classify": self._classify,
        }

    async def _extract(
        self,
        ctx: ProviderContext,
        content: str | RefResult | object,
        prompt: str,
        id: str | None = None,  # noqa: A002 - template API
        model: str | None = None,
    ) -> str:
        serialized = _serialize_for_llm(content)
        return await ctx.extract(serialized, prompt, call_id=id, model=model)

    async def _classify(
        self,
        ctx: ProviderContext,
        content: str | RefResult | object,
        labels: list[str | bool],
        id: str | None = None,  # noqa: A002 - template API
        model: str | None = None,
        multi: bool = False,
    ) -> str | bool | list[str | bool]:
        serialized = _serialize_for_llm(content)
        return await ctx.classify(serialized, labels, call_id=id, model=model, multi=multi)
