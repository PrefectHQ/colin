"""Base LLM provider interface."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class LLMResult(BaseModel):
    """Result from an LLM call."""

    text: str
    """The generated text."""

    model: str
    """Model that was used."""

    cost: float = 0.0
    """Cost in USD."""


class LLMProvider(Protocol):
    """Protocol for LLM providers."""

    async def complete(self, prompt: str, model: str = "default") -> LLMResult:
        """Generate a completion for a prompt.

        Args:
            prompt: The prompt to complete.
            model: Model to use.

        Returns:
            LLMResult with the generated text.
        """
        ...

    async def extract(
        self,
        content: str,
        extraction_prompt: str,
        previous_output: str | None = None,
    ) -> LLMResult:
        """Extract information from content.

        Args:
            content: The content to extract from.
            extraction_prompt: What to extract.
            previous_output: Previous extraction output for stability.

        Returns:
            LLMResult with the extracted text.
        """
        ...
