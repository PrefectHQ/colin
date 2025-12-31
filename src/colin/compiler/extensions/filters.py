"""LLM filters for Jinja templates."""

from __future__ import annotations

from typing import TYPE_CHECKING

from colin.models import RefResult

if TYPE_CHECKING:
    from colin.compiler.context import CompileContext


def _serialize_for_llm(value: str | RefResult | object) -> str:
    """Serialize a value for LLM consumption.

    For RefResult, includes name, description, content, and uri.
    Excludes template source to avoid confusion.
    """
    if isinstance(value, RefResult):
        parts = [f"# {value.name}"]
        if value.description:
            parts.append(f"Description: {value.description}")
        parts.append(f"URI: {value.uri}")
        parts.append("")
        parts.append(value.content)
        return "\n".join(parts)
    return str(value)


def create_extract_filter(context: CompileContext):
    """Create the extract filter bound to a compile context.

    Args:
        context: The compile context to use for LLM calls.

    Returns:
        An async filter function.
    """

    async def extract_filter(
        content: str | RefResult | object,
        prompt: str,
        id: str | None = None,  # noqa: A002 - using 'id' to match template syntax
        model: str | None = None,
    ) -> str:
        """Extract information from content using LLM.

        Usage in templates:
            {{ content | extract('feature requests') }}
            {{ content | extract('status', id='status-extraction') }}
            {{ ref('doc') | extract('summary', model='openai:gpt-4o') }}

        Args:
            content: The content to extract from (string or RefResult).
            prompt: What to extract.
            id: Optional manual ID for caching.
            model: Optional model override.

        Returns:
            The extracted text.
        """
        serialized = _serialize_for_llm(content)
        return await context.extract(serialized, prompt, call_id=id, model=model)

    return extract_filter


def create_classify_filter(context: CompileContext):
    """Create the classify filter bound to a compile context.

    Args:
        context: The compile context to use for LLM calls.

    Returns:
        An async filter function.
    """

    async def classify_filter(
        content: str | RefResult | object,
        labels: list[str | bool],
        id: str | None = None,  # noqa: A002 - using 'id' to match template syntax
        model: str | None = None,
        multi: bool = False,
    ) -> str | bool | list[str | bool]:
        """Classify content into predefined labels using LLM.

        Usage in templates:
            {{ content | classify(labels=['movie', 'book', 'podcast']) }}
            {{ content | classify(labels=['positive', 'negative'], id='sentiment') }}
            {{ ref('doc') | classify(labels=[True, False]) }}
            {{ ref('doc') | classify(labels=['tag1', 'tag2'], multi=True) }}

        Args:
            content: The content to classify (string or RefResult).
            labels: List of valid labels to choose from (strings or booleans).
            id: Optional manual ID for caching.
            model: Optional model override.
            multi: Whether to allow multiple labels (multi-label classification).

        Returns:
            Single label (str or bool) if multi=False, list of labels if multi=True.
        """
        serialized = _serialize_for_llm(content)
        return await context.classify(serialized, labels, call_id=id, model=model, multi=multi)

    return classify_filter
