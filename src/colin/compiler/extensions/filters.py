"""LLM filters for Jinja templates.

These filters provide position-based IDs for LLM calls, enabling previous_output
to be passed even when inputs change. Each filter factory maintains a counter
that resets per document (since filters are recreated for each compilation).

Loop awareness: When used inside {% for %} blocks, the position ID includes
the loop index (e.g., 'extract_1:0', 'extract_1:1') so each iteration gets
its own cache slot and previous_output history.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jinja2 import pass_context

if TYPE_CHECKING:
    from jinja2.runtime import Context


def create_llm_extract_filter(llm_namespace: Any):
    """Create the llm_extract filter bound to the LLM provider.

    The filter maintains a counter for position-based IDs, enabling previous_output
    to work across compilations even when inputs change. Loop index is automatically
    appended when inside a {% for %} block.

    Args:
        llm_namespace: The LLM provider namespace.

    Returns:
        An async filter function decorated with pass_context.
    """
    counter = 0

    @pass_context
    async def llm_extract_filter(
        context: Context,
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
            context: Jinja context (injected by @pass_context).
            content: The content to extract from.
            prompt: What to extract.
            model: Optional model override.
            instructions: Optional instructions override (call-level).
            _cache_id: Optional custom cache ID. If not provided, a position-based
                ID is generated automatically.
            _cache: Set to False to bypass cache.

        Returns:
            The extracted text.
        """
        nonlocal counter
        counter += 1

        # Build position ID with loop index if in a loop
        if _cache_id:
            effective_position_id = _cache_id
        else:
            base_id = f"extract_{counter}"
            loop = context.get("loop")
            if loop is not None:
                effective_position_id = f"{base_id}:{loop.index0}"
            else:
                effective_position_id = base_id

        return await llm_namespace.extract(
            content,
            prompt,
            model=model,
            instructions=instructions,
            _position_id=effective_position_id,
            _cache=_cache,
        )

    return llm_extract_filter


def create_llm_classify_filter(llm_namespace: Any):
    """Create the llm_classify filter bound to the LLM provider.

    The filter maintains a counter for position-based IDs, enabling previous_output
    to work across compilations even when inputs change. Loop index is automatically
    appended when inside a {% for %} block.

    Args:
        llm_namespace: The LLM provider namespace.

    Returns:
        An async filter function decorated with pass_context.
    """
    counter = 0

    @pass_context
    async def llm_classify_filter(
        context: Context,
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
            context: Jinja context (injected by @pass_context).
            content: The content to classify.
            labels: List of valid labels to choose from (strings or booleans).
            model: Optional model override.
            multi: Whether to allow multiple labels (multi-label classification).
            instructions: Optional instructions override (call-level).
            _cache_id: Optional custom cache ID. If not provided, a position-based
                ID is generated automatically.
            _cache: Set to False to bypass cache.

        Returns:
            Single label (str or bool) if multi=False, list of labels if multi=True.
        """
        nonlocal counter
        counter += 1

        # Build position ID with loop index if in a loop
        if _cache_id:
            effective_position_id = _cache_id
        else:
            base_id = f"classify_{counter}"
            loop = context.get("loop")
            if loop is not None:
                effective_position_id = f"{base_id}:{loop.index0}"
            else:
                effective_position_id = base_id

        return await llm_namespace.classify(
            content,
            labels,
            model=model,
            multi=multi,
            instructions=instructions,
            _position_id=effective_position_id,
            _cache=_cache,
        )

    return llm_classify_filter
