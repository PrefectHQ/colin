"""JSON renderer with markdown-to-JSON conversion."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from colin.renders.base import Renderer, RenderResult
from colin.renders.markdown_parser import parse_markdown_to_structure

if TYPE_CHECKING:
    from colin.models import OutputConfig


class JSONRenderer(Renderer):
    """Renderer for JSON output with markdown structure parsing.

    Parses markdown structure (headers, lists, fences) into JSON:
    - Headers become object keys
    - Markdown lists become arrays
    - JSON fences are parsed as literals
    - {% item %} blocks create array elements

    If no markdown structure is detected, tries to parse as literal JSON.
    Falls back to string literal with a warning if neither works.
    """

    name: str = "json"
    extension: str = ".json"

    def render(
        self,
        content: str,
        uri: str,
        output_config: OutputConfig | None = None,
    ) -> RenderResult:
        """Transform markdown content to JSON.

        Args:
            content: Raw template output (markdown-structured content).
            uri: Document URI for filename generation.
            output_config: Output configuration (format, path, publish).

        Returns:
            RenderResult with JSON content.

        Raises:
            MarkdownStructureError: For structural issues.
            json.JSONDecodeError: For invalid JSON in fences.
        """
        # Parse markdown structure to Python object
        structure = parse_markdown_to_structure(content)

        # Serialize to JSON
        json_content = json.dumps(structure, indent=2, ensure_ascii=False)

        return RenderResult(
            filename=self._get_output_filename(uri, output_config),
            content=json_content,
        )
