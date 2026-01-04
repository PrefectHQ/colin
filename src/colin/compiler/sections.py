"""Sections accessor for format-aware section access."""

from __future__ import annotations

from typing import Any


class SectionsAccessor:
    """Provides dot/dict access to sections with format-aware parsing.

    Supports both access patterns:
    - Dot: resource.sections.strategy
    - Dict: resource.sections['key metrics']

    Returns format-aware values:
    - JSON/YAML: Parsed data (dict/list/primitives)
    - Markdown: Raw string content

    Example:
        >>> sections = SectionsAccessor({"strategy": "## Focus\\nGrowth"}, "markdown")
        >>> sections.strategy
        '## Focus\\nGrowth'

        >>> sections = SectionsAccessor({"metrics": "## Revenue\\n$1M"}, "json")
        >>> sections.metrics
        {'Revenue': '$1M'}
    """

    def __init__(self, sections_data: dict[str, str], output_format: str) -> None:
        """Initialize the accessor.

        Args:
            sections_data: Dict mapping section names to their raw content.
            output_format: Output format (json, yaml, or markdown).
        """
        self._sections = sections_data
        self._format = output_format
        self._parsed_cache: dict[str, Any] = {}

    def __getattr__(self, name: str) -> Any:
        """Dot access: sections.strategy

        Args:
            name: Section name.

        Returns:
            Section content (raw string for markdown, parsed for json/yaml).

        Raises:
            AttributeError: If section not found.
        """
        if name.startswith("_"):
            raise AttributeError(f"No attribute '{name}'")
        return self._get_section(name)

    def __getitem__(self, name: str) -> Any:
        """Dict access: sections['key metrics']

        Args:
            name: Section name.

        Returns:
            Section content (raw string for markdown, parsed for json/yaml).

        Raises:
            KeyError: If section not found.
        """
        return self._get_section(name)

    def keys(self):
        """Return section names for iteration.

        Returns:
            Iterator of section names.
        """
        return self._sections.keys()

    def _get_section(self, name: str) -> Any:
        """Get section by name with format-aware parsing.

        Args:
            name: Section name.

        Returns:
            Section content (raw string for markdown, parsed for json/yaml).

        Raises:
            KeyError: If section not found.
        """
        if name not in self._sections:
            available = list(self._sections.keys())
            raise KeyError(f"Section '{name}' not found. Available sections: {available}")

        raw_content = self._sections[name]

        # Format-aware return
        if self._format == "markdown":
            return raw_content
        else:  # json or yaml
            # Parse markdown structure for structured formats
            if name not in self._parsed_cache:
                from colin.renders.markdown_parser import parse_markdown_to_structure

                self._parsed_cache[name] = parse_markdown_to_structure(raw_content)
            return self._parsed_cache[name]
