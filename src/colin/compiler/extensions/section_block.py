"""Section block extension for Jinja - creates named sections for cross-document refs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jinja2 import nodes
from jinja2.exceptions import TemplateSyntaxError
from jinja2.ext import Extension

if TYPE_CHECKING:
    from jinja2 import Environment
    from jinja2.parser import Parser

# Markers used to delimit sections in rendered output
SECTION_START_MARKER = "<!--COLIN:SECTION_START:{name}-->"
SECTION_END_MARKER = "<!--COLIN:SECTION_END:{name}-->"


class SectionBlockExtension(Extension):
    """Jinja extension for {% section name %}...{% endsection %} blocks.

    Usage:
        {% section strategy %}
        ## Our Strategy
        We're going to focus on growth...
        {% endsection %}

        {% section "key metrics" %}
        ## Revenue
        $1M
        {% endsection %}

    Sections are accessible from other documents via ref():
        {{ ref("plan.md").sections.strategy }}
        {{ ref("plan.md").sections['key metrics'] }}

    Sections use HTML comment markers (like item blocks) that are parsed
    after rendering to extract section names and content.
    """

    tags = {"section"}

    def __init__(self, environment: Environment) -> None:
        """Initialize the extension."""
        super().__init__(environment)

    def parse(self, parser: Parser) -> nodes.Node:
        """Parse the {% section name %} block."""
        lineno = next(parser.stream).lineno

        # Parse section name (identifier or string literal)
        if parser.stream.current.test("name"):
            # Bare identifier: {% section strategy %}
            name = nodes.Const(parser.stream.current.value)
            parser.stream.skip()
        elif parser.stream.current.test("string"):
            # String literal: {% section "key metrics" %}
            name = nodes.Const(parser.stream.current.value)
            parser.stream.skip()
        else:
            raise TemplateSyntaxError(
                "Expected section name (identifier or string)",
                lineno=lineno,
            )

        # Parse body until {% endsection %}
        body = parser.parse_statements(("name:endsection",), drop_needle=True)

        # Return CallBlock that invokes _render_section with name
        return nodes.CallBlock(
            self.call_method("_render_section", [name], []),
            [],
            [],
            body,
        ).set_lineno(lineno)

    async def _render_section(self, section_name: str, caller: object = None) -> str:
        """Called during template rendering.

        Wraps the block body in markers that will be parsed after rendering.

        Args:
            section_name: Name of the section.
            caller: Async callable that renders the block body.

        Returns:
            The rendered content wrapped in section markers.
        """
        if caller is None:
            raise RuntimeError("No caller provided to section block")

        # Render the block body
        body_content = await caller()

        # Wrap in markers for post-processing (like ItemBlockExtension)
        start = SECTION_START_MARKER.format(name=section_name)
        end = SECTION_END_MARKER.format(name=section_name)
        return f"{start}\n{body_content}\n{end}"
