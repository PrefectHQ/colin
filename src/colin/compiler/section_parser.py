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


def remove_colin_markers(content: str) -> str:
    """Remove all Colin internal markers from rendered content.

    Colin uses HTML comment markers for internal tracking (sections, items, etc.).
    These must be stripped before passing content to format renderers (JSON/YAML)
    since the markdown parser raises errors when seeing non-header content.

    Note: Item markers are consumed by the markdown parser's _parse_items(),
    but we strip them here too for defensive programming.

    Args:
        content: The rendered template output with markers.

    Returns:
        Content with all Colin markers removed but content preserved.

    Example:
        >>> content = '''<!--COLIN:SECTION_START:strategy-->
        ... ## Our Strategy
        ... <!--COLIN:SECTION_END:strategy-->'''
        >>> remove_colin_markers(content)
        '## Our Strategy'
    """
    # Remove all Colin markers (sections, items, and any future marker types)
    pattern = r"<!--COLIN:[^>]+-->\n?"
    return re.sub(pattern, "", content)
