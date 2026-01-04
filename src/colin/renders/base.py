"""Renderer base class for transforming compiled content."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from colin.models import Frontmatter


@dataclass
class RenderResult:
    """Result of rendering a document."""

    filename: str
    """Output filename (e.g., 'greeting.json')."""

    content: str
    """Rendered content."""


class Renderer:
    """Base class for content renderers.

    Renderers transform raw template output into final artifacts. They:
    - Transform content (e.g., markdown structure → JSON)
    - Determine the output filename (applying their extension)

    Rendering is part of compilation. The result is the final artifact
    stored in .colin/compiled/ and copied to output/.

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

    def render(
        self,
        content: str,
        uri: str,
        frontmatter: Frontmatter | None = None,
    ) -> RenderResult:
        """Transform content to final format.

        Default implementation passes through content unchanged.
        Override to transform content (e.g., parse markdown to JSON).

        Args:
            content: Raw template output.
            uri: Document URI for filename generation.
            frontmatter: Document frontmatter for validation/config.

        Returns:
            RenderResult with filename and rendered content.
        """
        return RenderResult(
            filename=self._get_output_filename(uri),
            content=content,
        )

    def _get_output_filename(self, uri: str) -> str:
        """Get output filename from URI, applying this renderer's extension."""
        path_part = uri.replace("project://", "")
        stem = Path(path_part).stem
        # Preserve directory structure
        parent = Path(path_part).parent
        if parent == Path("."):
            return f"{stem}{self.extension}"
        return f"{parent}/{stem}{self.extension}"
