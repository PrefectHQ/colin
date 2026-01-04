"""LLM filters for Jinja templates."""

from __future__ import annotations

from typing import Any


def create_llm_extract_filter(llm_namespace: Any):
    """Create the llm_extract filter bound to the LLM provider.

    Args:
        llm_namespace: The LLM provider namespace.

    Returns:
        An async filter function.
    """

    async def llm_extract_filter(
        content: object,
        prompt: str,
        model: str | None = None,
        instructions: str | None = None,
        _cache_id: str | None = None,
        _cache: bool = True,
    ) -> str:
        """Extract information from content using LLM.

        Usage in templates:
            {{ content | llm_extract('feature requests') }}
            {{ content | llm_extract('status', _cache_id='status-extraction') }}
            {{ ref('doc') | llm_extract('summary', model='openai:gpt-4o') }}
            {{ content | llm_extract('summary', _cache=False) }}
            {{ content | llm_extract('summary', instructions='Be concise.') }}

        Args:
            content: The content to extract from.
            prompt: What to extract.
            model: Optional model override.
            instructions: Optional instructions override (call-level).
            _cache_id: Optional custom cache ID.
            _cache: Set to False to bypass cache.

        Returns:
            The extracted text.
        """
        return await llm_namespace.extract(
            content,
            prompt,
            model=model,
            instructions=instructions,
            _cache_id=_cache_id,
            _cache=_cache,
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
        content: object,
        labels: list[str | bool],
        model: str | None = None,
        multi: bool = False,
        instructions: str | None = None,
        _cache_id: str | None = None,
        _cache: bool = True,
    ) -> str | bool | list[str | bool]:
        """Classify content into predefined labels using LLM.

        Usage in templates:
            {{ content | llm_classify(labels=['movie', 'book', 'podcast']) }}
            {{ content | llm_classify(labels=['positive', 'negative'], _cache_id='sentiment') }}
            {{ ref('doc') | llm_classify(labels=[True, False]) }}
            {{ ref('doc') | llm_classify(labels=['tag1', 'tag2'], multi=True) }}
            {{ content | llm_classify(labels=['a', 'b'], instructions='Be strict.') }}

        Args:
            content: The content to classify.
            labels: List of valid labels to choose from (strings or booleans).
            model: Optional model override.
            multi: Whether to allow multiple labels (multi-label classification).
            instructions: Optional instructions override (call-level).
            _cache_id: Optional custom cache ID.
            _cache: Set to False to bypass cache.

        Returns:
            Single label (str or bool) if multi=False, list of labels if multi=True.
        """
        return await llm_namespace.classify(
            content,
            labels,
            model=model,
            multi=multi,
            instructions=instructions,
            _cache_id=_cache_id,
            _cache=_cache,
        )

    return llm_classify_filter
