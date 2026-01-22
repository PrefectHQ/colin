"""Defer block extension for Jinja - deferred rendering with rendered context."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jinja2 import nodes
from jinja2.ext import Extension

if TYPE_CHECKING:
    from jinja2 import Environment
    from jinja2.parser import Parser

# Markers used to delimit defer blocks in rendered output
DEFER_START_MARKER = "<!--COLIN:DEFER_START:{id}-->"
DEFER_END_MARKER = "<!--COLIN:DEFER_END:{id}-->"


class DeferBlockExtension(Extension):
    """Jinja extension for {% defer %}...{% enddefer %} blocks.

    Defer blocks are rendered in a second pass after the document is rendered,
    with access to the `rendered` variable containing the document's output
    and sections.

    Usage:
        {% defer %}
        ## Table of Contents
        {% for key in rendered.sections.keys() %}
        - {{ key }}
        {% endfor %}
        {% enddefer %}

    The `rendered` variable contains:
        - rendered.content: Full document output from first pass
        - rendered.sections: SectionsAccessor for format-aware section access

    To access previous output, use the output() function:
        {{ output(cached=True) }}  # Previous Colin output
        {{ output() }}             # Published output (may have manual edits)
    """

    tags = {"defer"}

    def __init__(self, environment: Environment) -> None:
        """Initialize the extension."""
        super().__init__(environment)
        self._defer_counter = 0

    def parse(self, parser: Parser) -> nodes.Node:
        """Parse the {% defer %} block."""
        lineno = next(parser.stream).lineno

        # Generate unique ID for this defer block
        self._defer_counter += 1
        defer_id = f"defer_{self._defer_counter}_{lineno}"

        # Parse body until {% enddefer %}
        body = parser.parse_statements(("name:enddefer",), drop_needle=True)

        # Return CallBlock that will:
        # - First pass: emit marker placeholder and store callable
        # - Second pass: invoke callable with rendered as parameter
        # The caller receives 'rendered' as a block parameter
        return nodes.CallBlock(
            self.call_method("_render_defer", [nodes.Const(defer_id)], []),
            [nodes.Name("rendered", "param")],
            [],
            body,
        ).set_lineno(lineno)

    async def _render_defer(self, defer_id: str, rendered=None, caller: object = None) -> str:
        """Called during template rendering.

        First pass: Store the callable and emit a placeholder marker.
        Second pass: Invoke callable with rendered as parameter.

        Args:
            defer_id: Unique identifier for this defer block.
            rendered: RenderedOutput for current rendering (None in first pass).
            caller: Async callable that renders the block body, receives rendered.

        Returns:
            Placeholder marker (first pass) or rendered content (second pass).
        """
        if caller is None:
            raise RuntimeError("No caller provided to defer block")

        # Import here to avoid circular dependency
        from colin.compiler.cache import get_compile_context

        context = get_compile_context()

        # First pass: store callable and return marker
        if context is not None and hasattr(context, "defer_blocks"):
            if defer_id not in context.defer_blocks:
                # First pass: store callable for second pass
                context.defer_blocks[defer_id] = caller
                start = DEFER_START_MARKER.format(id=defer_id)
                end = DEFER_END_MARKER.format(id=defer_id)
                return f"{start}{end}"

        # Second pass (or no context): render with provided rendered
        return await caller(rendered)
