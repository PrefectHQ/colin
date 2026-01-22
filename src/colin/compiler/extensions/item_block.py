"""Item block extension for Jinja - creates array items in JSON output."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jinja2 import nodes
from jinja2.ext import Extension

if TYPE_CHECKING:
    from jinja2 import Environment
    from jinja2.parser import Parser

# Markers used to delimit array items in rendered output
ITEM_START_MARKER = "<!--COLIN:ITEM_START-->"
ITEM_END_MARKER = "<!--COLIN:ITEM_END-->"


class ItemBlockExtension(Extension):
    """Jinja extension for {% item %}...{% enditem %} blocks.

    Usage:
        {% for row in rows %}
        {% item %}
        ## id
        {{ row.id }}

        ## summary
        {{ row.summary }}
        {% enditem %}
        {% endfor %}

    When used with output: json, each item block becomes an array element.
    The content inside is parsed as markdown structure (headers → keys).
    """

    tags = {"item"}

    def __init__(self, environment: Environment) -> None:
        """Initialize the extension."""
        super().__init__(environment)

    def parse(self, parser: Parser) -> nodes.Node:
        """Parse the {% item %} block."""
        lineno = next(parser.stream).lineno

        # Parse body until {% enditem %}
        body = parser.parse_statements(("name:enditem",), drop_needle=True)

        # Return CallBlock that invokes our _render_item method
        return nodes.CallBlock(
            self.call_method("_render_item", [], []),
            [],
            [],
            body,
        ).set_lineno(lineno)

    async def _render_item(self, caller: object = None) -> str:
        """Called during template rendering.

        Wraps the block body in markers that the JSON renderer can detect.

        Args:
            caller: Async callable that renders the block body.

        Returns:
            The rendered content wrapped in item markers.
        """
        if caller is None:
            raise RuntimeError("No caller provided to item block")

        # Render the block body
        body_content = await caller()

        # Wrap in markers for the renderer to detect
        return f"{ITEM_START_MARKER}\n{body_content}\n{ITEM_END_MARKER}"
