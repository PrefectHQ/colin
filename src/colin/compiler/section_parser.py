"""Parse section markers from rendered template output."""

from __future__ import annotations

import re


def parse_sections(content: str) -> dict[str, str]:
    """Extract sections from rendered content with markers.

    Finds all <!--COLIN:SECTION_START:name-->...<!--COLIN:SECTION_END:name--> blocks
    and returns a dict mapping section names to their content.

    Args:
        content: The rendered template output with section markers.

    Returns:
        Dictionary mapping section names to their content (stripped).
        If duplicate section names exist, last definition wins.

    Example:
        >>> content = '''
        ... <!--COLIN:SECTION_START:strategy-->
        ... ## Our Strategy
        ... Focus on growth
        ... <!--COLIN:SECTION_END:strategy-->
        ... '''
        >>> sections = parse_sections(content)
        >>> sections['strategy']
        '## Our Strategy\\nFocus on growth'
    """
    pattern = r"<!--COLIN:SECTION_START:(.+?)-->\n?(.*?)\n?<!--COLIN:SECTION_END:\1-->"
    sections = {}

    for match in re.finditer(pattern, content, re.DOTALL):
        section_name = match.group(1)
        section_content = match.group(2).strip()
        sections[section_name] = section_content  # Last wins if duplicates

    return sections
