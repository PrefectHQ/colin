"""LLM provider functions for templates."""

from collections.abc import Awaitable, Callable

from colin.compiler.extensions.filters import _serialize_for_llm
from colin.models import RefResult
from colin.providers.base import Provider
from colin.providers.context import ProviderContext


class LLMProvider(Provider):
    """Provider wrapper for LLM template functions."""

    scheme = "llm"

    async def read(self, path: str) -> str:
        raise ValueError("LLM provider does not support read()")

    def get_functions(self) -> dict[str, Callable[..., Awaitable[object]]]:
        return {
            "extract": self._extract,
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
        return await ctx.extract(serialized, prompt, id, model)
