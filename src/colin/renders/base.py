"""Renderer base class for transforming compiled content."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from colin.models import CompiledDocument


@dataclass
class RenderResult:
    """Result of rendering a document."""

    filename: str
    """Output filename (e.g., 'greeting.json')."""

    content: str
    """Rendered content."""


class Renderer:
    """Base class for content renderers.

    Renderers transform compiled content and determine the output filename.
    They can change file extensions and validate/format content.

    The default render() passes through content unchanged. Subclasses can
    override to transform content or just override validate() for format
    checking without transformation.

    Subclasses must set `name`.
    """

    name: str
    """Renderer name for lookup (e.g., 'json', 'markdown')."""

    extension: str = ".md"
    """File extension including dot (e.g., '.md', '.json')."""

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if not hasattr(cls, "name") or not isinstance(getattr(cls, "name", None), str):
            raise TypeError(f"{cls.__name__} must define 'name: str'")

    def render(self, document: CompiledDocument) -> RenderResult:
        """Transform document content and determine output filename.

        Default implementation validates and passes through content unchanged.
        Override to transform content.

        Args:
            document: The compiled document.

        Returns:
            RenderResult with filename and content.
        """
        self.validate(document)
        return RenderResult(
            filename=self._get_output_filename(document.uri),
            content=document.output,
        )

    def validate(self, document: CompiledDocument) -> None:
        """Validate document for this output format.

        Override in subclasses to validate output format (e.g., JSON, YAML).
        Can check frontmatter for validation settings (e.g., skip validation).
        Raises an exception if content is invalid; returns None if valid.

        Args:
            document: The compiled document (includes output and frontmatter).

        Raises:
            ValueError: If content is invalid for this renderer's format.
        """
        pass

    def _get_output_filename(self, uri: str) -> str:
        """Get output filename from URI, applying this renderer's extension."""
        path_part = uri.replace("project://", "")
        stem = Path(path_part).stem
        # Preserve directory structure
        parent = Path(path_part).parent
        if parent == Path("."):
            return f"{stem}{self.extension}"
        return f"{parent}/{stem}{self.extension}"
