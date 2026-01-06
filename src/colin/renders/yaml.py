"""YAML renderer with markdown-to-YAML conversion."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

from colin.renders.base import Renderer, RenderResult
from colin.renders.markdown_parser import parse_markdown_to_structure

if TYPE_CHECKING:
    from colin.models import OutputConfig


class YAMLRenderer(Renderer):
    """Renderer for YAML output with markdown structure parsing.

    Parses markdown structure (headers, lists, fences) into YAML:
    - Headers become mapping keys
    - Markdown lists become sequences
    - JSON/YAML fences are parsed as literals
    - {% item %} blocks create sequence elements

    If no markdown structure is detected, tries to parse as literal data.
    Falls back to string literal with a warning if neither works.
    """

    name: str = "yaml"
    extension: str = ".yaml"

    def render(
        self,
        content: str,
        uri: str,
        output_config: OutputConfig | None = None,
    ) -> RenderResult:
        """Transform markdown content to YAML.

        Args:
            content: Raw template output (markdown-structured content).
            uri: Document URI for filename generation.
            output_config: Output configuration (format, path, publish).

        Returns:
            RenderResult with YAML content.

        Raises:
            MarkdownStructureError: For structural issues.
            yaml.YAMLError: For invalid YAML in fences.
        """
        # Parse markdown structure to Python object
        structure = parse_markdown_to_structure(content)

        # Serialize to YAML
        yaml_content = yaml.dump(
            structure, default_flow_style=False, allow_unicode=True, sort_keys=False
        )

        return RenderResult(
            filename=self._get_output_filename(uri, output_config),
            content=yaml_content,
        )
