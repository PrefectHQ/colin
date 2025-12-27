"""LLM block extension for Jinja."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jinja2 import nodes
from jinja2.ext import Extension

if TYPE_CHECKING:
    from jinja2 import Environment
    from jinja2.parser import Parser


class LLMBlockExtension(Extension):
    """Jinja extension for {% llm %}...{% endllm %} blocks.

    Usage:
        {% llm %}
        Your prompt here with {{ ref('something') }}
        {% endllm %}

        {% llm model="sonnet" id="my-id" %}
        Prompt with explicit model and ID.
        {% endllm %}

    The body is rendered first (resolving any refs/expressions),
    then passed to the LLM for processing.
    """

    tags = {"llm"}

    def __init__(self, environment: Environment) -> None:
        """Initialize the extension."""
        super().__init__(environment)

    def parse(self, parser: Parser) -> nodes.Node:
        """Parse the {% llm %} block."""
        lineno = next(parser.stream).lineno

        # Parse optional keyword arguments: model, id
        kwargs: list[nodes.Keyword] = []

        while parser.stream.current.test("name"):
            key = parser.stream.current.value
            parser.stream.skip()
            parser.stream.expect("assign")
            value = parser.parse_expression()
            kwargs.append(nodes.Keyword(key, value, lineno=lineno))

            # Handle optional comma between kwargs
            if parser.stream.current.test("comma"):
                parser.stream.skip()

        # Parse body until {% endllm %}
        body = parser.parse_statements(("name:endllm",), drop_needle=True)

        # Return CallBlock that invokes our _render_llm method
        return nodes.CallBlock(
            self.call_method("_render_llm", [], kwargs),
            [],
            [],
            body,
        ).set_lineno(lineno)

    async def _render_llm(
        self,
        model: str | None = None,
        id: str | None = None,  # noqa: A002 - using 'id' to match template syntax
        caller: object = None,
    ) -> str:
        """Called during template rendering.

        Args:
            model: LLM model name (ignored for stub).
            id: Optional manual ID for caching.
            caller: Async callable that renders the block body.

        Returns:
            The LLM response (or stub response).
        """
        # Get the rendered body content (with refs resolved)
        # In async mode, caller() returns a coroutine
        if caller is None:
            return "[ERROR: No caller provided to LLM block]"

        # caller is actually an async callable
        body_content = await caller()  # type: ignore[misc]

        # Access the compile context from the environment
        # This is attached by the compiler before rendering
        compile_context = getattr(self.environment, "compile_context", None)

        if compile_context is None:
            # No context available, return a placeholder
            return f"[LLM BLOCK - no context]\n{body_content}"

        # Delegate to context's LLM handling
        return await compile_context.call_llm_block(
            body=body_content,
            model=model or "stub",
            call_id=id,
        )

