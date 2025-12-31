"""LLM filters for Jinja templates."""

from __future__ import annotations

from typing import Any

from colin.models import RefResult


def create_llm_extract_filter(llm_namespace: Any):
    """Create the llm_extract filter bound to the LLM provider.

    Args:
        llm_namespace: The LLM provider namespace.

    Returns:
        An async filter function.
    """

    async def llm_extract_filter(
        content: str | RefResult | object,
        prompt: str,
        model: str | None = None,
        _cache_id: str | None = None,
        _cache: bool = True,
    ) -> str:
        """Extract information from content using LLM.

        Usage in templates:
            {{ content | llm_extract('feature requests') }}
            {{ content | llm_extract('status', _cache_id='status-extraction') }}
            {{ ref('doc') | llm_extract('summary', model='openai:gpt-4o') }}
            {{ content | llm_extract('summary', _cache=False) }}

        Args:
            content: The content to extract from (string or RefResult).
            prompt: What to extract.
            model: Optional model override.
            _cache_id: Optional custom cache ID.
            _cache: Set to False to bypass cache.

        Returns:
            The extracted text.
        """
        return await llm_namespace.extract(
            content, prompt, model=model, _cache_id=_cache_id, _cache=_cache
        )

    return llm_extract_filter


def create_llm_classify_filter(llm_namespace: Any):
    """Create the llm_classify filter bound to the LLM provider.

    Args:
        llm_namespace: The LLM provider namespace.

    Returns:
        An async filter function.
    """

    async def llm_classify_filter(
        content: str | RefResult | object,
        labels: list[str | bool],
        model: str | None = None,
        multi: bool = False,
        _cache_id: str | None = None,
        _cache: bool = True,
    ) -> str | bool | list[str | bool]:
        """Classify content into predefined labels using LLM.

        Usage in templates:
            {{ content | llm_classify(labels=['movie', 'book', 'podcast']) }}
            {{ content | llm_classify(labels=['positive', 'negative'], _cache_id='sentiment') }}
            {{ ref('doc') | llm_classify(labels=[True, False]) }}
            {{ ref('doc') | llm_classify(labels=['tag1', 'tag2'], multi=True) }}

        Args:
            content: The content to classify (string or RefResult).
            labels: List of valid labels to choose from (strings or booleans).
            model: Optional model override.
            multi: Whether to allow multiple labels (multi-label classification).
            _cache_id: Optional custom cache ID.
            _cache: Set to False to bypass cache.

        Returns:
            Single label (str or bool) if multi=False, list of labels if multi=True.
        """
        return await llm_namespace.classify(
            content, labels, model=model, multi=multi, _cache_id=_cache_id, _cache=_cache
        )

    return llm_classify_filter
