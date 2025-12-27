"""Stub LLM provider for testing."""

from __future__ import annotations

import hashlib

from colin.llm.base import LLMResult


class StubLLMProvider:
    """Stub LLM provider for testing.

    Returns deterministic output based on input hash, making tests reproducible.
    """

    async def complete(self, prompt: str, model: str = "stub") -> LLMResult:
        """Return a stub completion.

        Args:
            prompt: The prompt to complete.
            model: Model name (ignored, always uses 'stub').

        Returns:
            LLMResult with deterministic stub output.
        """
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:8]

        return LLMResult(
            text=(
                f"[STUB LLM RESPONSE: {prompt_hash}]\n\n"
                f"This is a stub response for testing.\n"
                f"Input length: {len(prompt)} chars\n"
                f"Model requested: {model}"
            ),
            model="stub",
            cost=0.0,
        )

    async def extract(
        self,
        content: str,
        extraction_prompt: str,
        previous_output: str | None = None,
    ) -> LLMResult:
        """Return a stub extraction.

        Args:
            content: The content to extract from.
            extraction_prompt: What to extract.
            previous_output: Previous extraction output (included in hash).

        Returns:
            LLMResult with deterministic stub output.
        """
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:8]
        prompt_hash = hashlib.sha256(extraction_prompt.encode()).hexdigest()[:8]

        prev_info = ""
        if previous_output:
            prev_hash = hashlib.sha256(previous_output.encode()).hexdigest()[:8]
            prev_info = f"\nPrevious output hash: {prev_hash}"

        return LLMResult(
            text=(
                f"[STUB EXTRACTION: content={content_hash}, prompt={prompt_hash}]\n\n"
                f"Extracted from {len(content)} chars of content.\n"
                f"Extraction prompt: {extraction_prompt[:50]}..."
                f"{prev_info}"
            ),
            model="stub",
            cost=0.0,
        )
