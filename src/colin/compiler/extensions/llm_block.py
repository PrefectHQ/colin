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

        {% llm instructions=ref('prompts/agent.md').content %}
        Prompt with instructions override.
        {% endllm %}

    The body is rendered first (resolving any refs/expressions),
    then passed to the LLM for processing.

    Position-based IDs:
        When no explicit ID is provided, a stable position-based ID is generated
        at parse time (e.g., 'llm_1_42' for the first LLM block at line 42).
        This enables previous_output to be passed to LLM calls even when the
        prompt content changes, allowing the LLM to produce stable outputs.
    """

    tags = {"llm"}

    def __init__(self, environment: Environment) -> None:
        """Initialize the extension."""
        super().__init__(environment)
        self._llm_counter = 0

    def parse(self, parser: Parser) -> nodes.Node:
        """Parse the {% llm %} block."""
        lineno = next(parser.stream).lineno

        # Generate position-based ID for this LLM block
        self._llm_counter += 1
        position_id = f"llm_{self._llm_counter}_{lineno}"

        # Parse optional keyword arguments: model, id
        kwargs: list[nodes.Keyword] = []
        has_explicit_id = False

        while parser.stream.current.test("name"):
            key = parser.stream.current.value
            parser.stream.skip()
            parser.stream.expect("assign")
            value = parser.parse_expression()
            kwargs.append(nodes.Keyword(key, value, lineno=lineno))

            # Track if user provided explicit ID
            if key in ("id", "_cache_id"):
                has_explicit_id = True

            # Handle optional comma between kwargs
            if parser.stream.current.test("comma"):
                parser.stream.skip()

        # If no explicit ID provided, pass position-based ID
        # Include loop index if we're inside a {% for %} block at runtime
        if not has_explicit_id:
            # Build: f"{position_id}:{loop.index0}" if loop is defined else position_id
            loop_var = nodes.Name("loop", "load", lineno=lineno)
            loop_index = nodes.Getattr(loop_var, "index0", "load", lineno=lineno)

            # Concatenation: position_id + ":" + str(loop.index0)
            concat = nodes.Concat(
                [nodes.Const(f"{position_id}:"), loop_index],
                lineno=lineno,
            )

            # Test: loop is defined
            is_defined = nodes.Test(loop_var, "defined", [], [], None, None, lineno=lineno)

            # Conditional: concat if is_defined else position_id
            position_expr = nodes.CondExpr(
                is_defined,
                concat,
                nodes.Const(position_id),
                lineno=lineno,
            )

            kwargs.append(nodes.Keyword("_position_id", position_expr, lineno=lineno))

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
        _cache_id: str | None = None,
        _position_id: str | None = None,
        _cache: bool = True,
        instructions: str | None = None,
        caller: object = None,
    ) -> str:
        """Called during template rendering.

        Args:
            model: LLM model name override.
            id: Alias for _cache_id (deprecated, use _cache_id).
            _cache_id: Optional custom cache ID.
            _position_id: Auto-generated position-based ID (set at parse time).
            _cache: Set to False to bypass cache.
            instructions: Optional instructions override (call-level).
            caller: Async callable that renders the block body.

        Returns:
            The LLM response.
        """
        # Get the rendered body content (with refs resolved)
        # In async mode, caller() returns a coroutine
        if caller is None:
            return "[ERROR: No caller provided to LLM block]"

        # caller is actually an async callable
        body_content = await caller()

        # Access the LLM namespace from the environment
        # This is attached by the compiler before rendering
        llm_namespace = getattr(self.environment, "llm_namespace", None)

        if llm_namespace is None:
            # No context available, return a placeholder
            return f"[LLM BLOCK - no context]\n{body_content}"

        # ID precedence: explicit _cache_id > explicit id > position-based ID
        # Position-based IDs enable previous_output to work even when prompt changes
        effective_position_id = _cache_id or id or _position_id

        # Delegate to LLM provider's complete method
        return await llm_namespace.complete(
            body_content,
            model=model,
            instructions=instructions,
            _position_id=effective_position_id,
            _cache=_cache,
        )
