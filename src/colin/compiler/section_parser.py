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


def remove_section_and_defer_markers(content: str) -> str:
    """Remove section and defer markers, but keep item markers for renderers.

    The markdown parser needs item markers to detect {% item %} arrays,
    so we only strip section and defer markers before rendering.

    Args:
        content: The rendered template output with markers.

    Returns:
        Content with section and defer markers removed, item markers preserved.

    Example:
        >>> content = '''<!--COLIN:SECTION_START:strategy-->
        ... ## Our Strategy
        ... <!--COLIN:SECTION_END:strategy-->'''
        >>> remove_section_and_defer_markers(content)
        '## Our Strategy'
    """
    # Remove only SECTION and DEFER markers (keep ITEM markers for the renderer)
    patterns = [
        r"<!--COLIN:SECTION_START:[^>]+-->\n?",
        r"<!--COLIN:SECTION_END:[^>]+-->\n?",
        r"<!--COLIN:DEFER_START:[^>]+-->\n?",
        r"<!--COLIN:DEFER_END:[^>]+-->\n?",
    ]
    for pattern in patterns:
        content = re.sub(pattern, "", content)
    return content


def remove_colin_markers(content: str) -> str:
    """Remove all Colin internal markers from rendered content.

    Colin uses HTML comment markers for internal tracking (sections, items, etc.).
    This function removes ALL markers and should only be called after rendering
    is complete.

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
