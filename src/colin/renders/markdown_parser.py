"""Parse markdown structure into Python data structures for structured output."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from colin.compiler.extensions.item_block import ITEM_END_MARKER, ITEM_START_MARKER

logger = logging.getLogger(__name__)


class MarkdownStructureError(Exception):
    """Error in markdown structure for JSON conversion."""

    def __init__(self, message: str, line: int | None = None):
        self.line = line
        if line is not None:
            message = f"Line {line}: {message}"
        super().__init__(message)


@dataclass
class Section:
    """A parsed markdown section."""

    key: str
    level: int
    content: str = ""
    children: list[Section] = field(default_factory=list)


def parse_markdown_to_structure(content: str) -> dict[str, Any] | list[Any] | str:
    """Parse markdown content into a Python structure for JSON conversion.

    Parsing rules (in order):
    1. If has headers → build nested dict (items inside headers are valid)
    2. If has ITEM markers (no headers) → split into array
    3. If only a json fence → json.loads() passthrough
    4. If valid JSON (try json.loads()) → pass through as-is
    5. Else → log warning + return as string literal

    Args:
        content: The markdown content to parse.

    Returns:
        A dict, list, or string representing the structured data.

    Raises:
        MarkdownStructureError: For structural issues (duplicate keys, etc.)
        json.JSONDecodeError: For invalid JSON in fences.
    """
    content = content.strip()

    if not content:
        return ""

    # Determine what structure comes first: headers or items
    has_headers = _has_headers(content)
    has_items = ITEM_START_MARKER in content

    if has_headers and has_items:
        # Check which comes first to determine root structure
        header_match = re.search(r"^#+\s+", content, re.MULTILINE)
        item_pos = content.find(ITEM_START_MARKER)

        header_pos = header_match.start() if header_match else len(content)

        if item_pos < header_pos:
            # Items come first → root is array, headers are inside items
            return _parse_items(content)
        else:
            # Headers come first → root is object, items are inside headers
            return _parse_headers(content)

    # Rule 1: Check for headers (items inside headers handled above)
    if has_headers:
        return _parse_headers(content)

    # Rule 2: Check for item markers
    if has_items:
        return _parse_items(content)

    # Rule 3: Check for data fence only (json or yaml, no headers)
    data_fence = _extract_sole_data_fence(content)
    if data_fence is not None:
        lang, fence_content = data_fence
        if lang == "yaml":
            return yaml.safe_load(fence_content)
        return json.loads(fence_content)

    # Rule 4: Try to parse as literal JSON (if it looks like JSON)
    # Note: content is already stripped at function start
    if content.startswith(("{", "[")):
        # Looks like JSON - parse it and let errors propagate
        return json.loads(content)

    # Rule 5: Try to parse as YAML
    try:
        parsed = yaml.safe_load(content)
        if parsed is not None and not isinstance(parsed, str):
            # Successfully parsed as structured YAML (dict, list, number, bool)
            return parsed
    except yaml.YAMLError:
        pass

    # Rule 6: Return as string with warning
    logger.warning(
        "No markdown structure detected for structured output. "
        "Content will be returned as a string literal. "
        "Consider using headers (## key) or a data fence."
    )
    return content


def _parse_items(content: str) -> list[Any]:
    """Parse content with item markers into a list.

    Args:
        content: Content containing ITEM markers.

    Returns:
        List of parsed items.

    Raises:
        MarkdownStructureError: If headers exist between items (at root level).
    """
    items: list[Any] = []
    parts = content.split(ITEM_START_MARKER)

    # Check for headers before first item (content before first marker)
    if parts[0].strip() and _has_headers(parts[0]):
        raise MarkdownStructureError("Cannot mix {% item %} blocks with headers at the root level")

    for part in parts[1:]:  # Skip content before first marker
        if ITEM_END_MARKER in part:
            item_content, remainder = part.split(ITEM_END_MARKER, 1)
            # Check for headers between items (in remainder)
            if remainder.strip() and _has_headers(remainder):
                # Only error if the remainder has headers outside of nested items
                remainder_outside_items = re.sub(
                    rf"{re.escape(ITEM_START_MARKER)}.*?{re.escape(ITEM_END_MARKER)}",
                    "",
                    remainder,
                    flags=re.DOTALL,
                )
                if _has_headers(remainder_outside_items):
                    raise MarkdownStructureError(
                        "Cannot mix {% item %} blocks with headers at the root level"
                    )
            # Recursively parse item content
            parsed = parse_markdown_to_structure(item_content)
            items.append(parsed)

    return items


def _extract_sole_data_fence(content: str) -> tuple[str, str] | None:
    """Extract content from a lone data fence (json or yaml, no headers).

    Returns None if:
    - No data fence exists
    - Headers exist alongside the fence
    - Multiple data fences exist

    Args:
        content: The content to check.

    Returns:
        Tuple of (language, fence_content), or None if not a sole data fence.
    """
    if _has_headers(content):
        return None

    # Find all json/yaml fences
    pattern = r"```(json|yaml)\s*\n(.*?)\n\s*```"
    matches = list(re.finditer(pattern, content, re.DOTALL))

    if len(matches) != 1:
        return None

    # Check that content is only whitespace outside the fence
    match = matches[0]
    before = content[: match.start()].strip()
    after = content[match.end() :].strip()

    if before or after:
        return None

    return (matches[0].group(1), matches[0].group(2))


def _has_headers(content: str) -> bool:
    """Check if content contains markdown headers.

    Args:
        content: The content to check.

    Returns:
        True if any markdown headers are found.
    """
    return bool(re.search(r"^#+\s+", content, re.MULTILINE))


def _parse_headers(content: str) -> dict[str, Any]:
    """Parse markdown headers into a nested dict structure.

    Args:
        content: Content with headers.

    Returns:
        Dict with headers as keys.

    Raises:
        MarkdownStructureError: For duplicate keys or content before first header.
    """
    lines = content.split("\n")
    sections = _parse_sections(lines)

    if not sections:
        return {}

    return _sections_to_dict(sections)


def _parse_sections(lines: list[str]) -> list[Section]:
    """Parse lines into a list of Section objects.

    Args:
        lines: Lines of content.

    Returns:
        List of top-level sections.

    Raises:
        MarkdownStructureError: If content exists before first header.
    """
    sections: list[Section] = []
    current_section: Section | None = None
    content_lines: list[str] = []
    min_level: int | None = None

    for line_num, line in enumerate(lines, start=1):
        header_match = re.match(r"^(#+)\s+(.+)$", line)

        if header_match:
            # Save previous section's content
            if current_section is not None:
                current_section.content = "\n".join(content_lines).strip()
                content_lines = []

            level = len(header_match.group(1))
            key = header_match.group(2).strip()

            if min_level is None:
                min_level = level
            elif level < min_level:
                min_level = level

            current_section = Section(key=key, level=level)
            sections.append(current_section)
        else:
            if current_section is None:
                # Content before first header
                if line.strip():
                    raise MarkdownStructureError(
                        "Content found before first header when using header structure",
                        line=line_num,
                    )
            else:
                content_lines.append(line)

    # Save last section's content
    if current_section is not None:
        current_section.content = "\n".join(content_lines).strip()

    # Build hierarchy based on header levels
    if sections and min_level is not None:
        return _build_section_hierarchy(sections, min_level)

    return sections


def _build_section_hierarchy(sections: list[Section], min_level: int) -> list[Section]:
    """Build a hierarchical structure from flat section list.

    Args:
        sections: Flat list of sections.
        min_level: The minimum (shallowest) header level.

    Returns:
        Hierarchical list with children populated.
    """
    root_sections: list[Section] = []
    stack: list[Section] = []

    for section in sections:
        # Pop stack until we find the right parent level
        while stack and stack[-1].level >= section.level:
            stack.pop()

        if section.level == min_level:
            root_sections.append(section)
        elif stack:
            stack[-1].children.append(section)
        else:
            root_sections.append(section)

        stack.append(section)

    return root_sections


def _sections_to_dict(sections: list[Section]) -> dict[str, Any]:
    """Convert sections to a dict, recursively.

    Args:
        sections: List of sections.

    Returns:
        Dict with section keys and values.

    Raises:
        MarkdownStructureError: If duplicate keys exist at the same level.
    """
    result: dict[str, Any] = {}

    for section in sections:
        if section.key in result:
            raise MarkdownStructureError(f"Duplicate key '{section.key}' at the same level")

        value = _section_value(section)
        result[section.key] = value

    return result


def _section_value(section: Section) -> Any:
    """Convert a section's content to an appropriate value.

    Args:
        section: The section to convert.

    Returns:
        The converted value (dict, list, string, or parsed JSON).
    """
    # If has children, value is a nested dict
    if section.children:
        child_dict = _sections_to_dict(section.children)
        # If there's also content, it becomes a special key or we merge
        if section.content.strip():
            # Content alongside children - put content first, merge children
            return {"_content": _parse_content(section.content), **child_dict}
        return child_dict

    # Otherwise, parse the content
    return _parse_content(section.content)


def _parse_content(content: str) -> Any:
    """Parse section content into an appropriate value.

    Args:
        content: The content to parse.

    Returns:
        Parsed value (list, data literal, or string).
    """
    content = content.strip()

    if not content:
        return ""

    # Check for data fence (json or yaml)
    fence_match = re.search(r"```(json|yaml)\s*\n(.*?)\n\s*```", content, re.DOTALL)
    if fence_match:
        # If fence is the only content, parse as data
        before = content[: fence_match.start()].strip()
        after = content[fence_match.end() :].strip()
        if not before and not after:
            lang = fence_match.group(1)
            fence_content = fence_match.group(2)
            if lang == "yaml":
                return yaml.safe_load(fence_content)
            return json.loads(fence_content)

    # Check for markdown list
    if _is_markdown_list(content):
        return _parse_markdown_list(content)

    # Check for item markers (nested items)
    if ITEM_START_MARKER in content:
        return _parse_items(content)

    return content


def _is_markdown_list(content: str) -> bool:
    """Check if content is a markdown list.

    Args:
        content: The content to check.

    Returns:
        True if content is a markdown list.
    """
    lines = content.strip().split("\n")
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("-"):
            return False
    return bool(lines) and any(line.strip() for line in lines)


def _parse_markdown_list(content: str) -> list[str]:
    """Parse a markdown list into a Python list.

    Args:
        content: The markdown list content.

    Returns:
        List of items.
    """
    items: list[str] = []
    for line in content.strip().split("\n"):
        stripped = line.strip()
        if stripped.startswith("-"):
            item = stripped[1:].strip()
            items.append(item)
    return items
