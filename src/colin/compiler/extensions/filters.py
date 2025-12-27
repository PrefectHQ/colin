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
    ) -> str:
        """Extract information from content using LLM.

        Usage in templates:
            {{ content | extract('feature requests') }}
            {{ content | extract('status', id='status-extraction') }}
            {{ ref('doc') | extract('summary') }}

        Args:
            content: The content to extract from (string or RefResult).
            prompt: What to extract.
            id: Optional manual ID for caching.

        Returns:
            The extracted text.
        """
        serialized = _serialize_for_llm(content)
        return await context.extract(serialized, prompt, call_id=id)

    return extract_filter

