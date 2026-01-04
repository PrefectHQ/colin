"""Rendered output wrapper for defer block access."""

from __future__ import annotations

from colin.compiler.sections import SectionsAccessor


class RenderedOutput:
    """Provides access to rendered document content and sections.

    Used in defer blocks to access the document's own rendered output via
    `rendered` (current compilation) and `previous_rendered` (last cached).

    Attributes:
        content: Full rendered output as string.
        sections: Format-aware accessor for document sections.

    Example:
        ```jinja
        {% defer %}
        ## Table of Contents
        {% for key in rendered.sections.keys() %}
        - {{ key }}
        {% endfor %}
        {% enddefer %}
        ```
    """

    def __init__(
        self,
        content: str,
        sections: dict[str, str],
        output_format: str = "markdown",
    ):
        """Initialize rendered output wrapper.

        Args:
            content: Full rendered document output.
            sections: Mapping of section names to their content.
            output_format: Output format for format-aware section parsing.
        """
        self._content = content
        self._sections_data = sections
        self._output_format = output_format
        self._sections_accessor: SectionsAccessor | None = None

    @property
    def content(self) -> str:
        """Full rendered output as string."""
        return self._content

    @property
    def sections(self) -> SectionsAccessor:
        """Format-aware access to sections.

        Returns:
            Accessor providing dot/dict access to sections with format-aware parsing.
        """
        if self._sections_accessor is None:
            self._sections_accessor = SectionsAccessor(
                self._sections_data,
                self._output_format,
            )
        return self._sections_accessor

    def __str__(self) -> str:
        """String representation returns content."""
        return self._content
