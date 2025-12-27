"""Markdown output plugin."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from colin.models import CompiledDocument


class MarkdownOutputPlugin:
    """Output plugin that writes compiled documents as raw markdown.

    This is the default output plugin. It writes the compiled output
    directly to the output directory with a .md extension.
    """

    name: str = "markdown"

    async def emit(
        self,
        doc: CompiledDocument,
        output_dir: Path,
    ) -> list[Path]:
        """Write compiled document as markdown.

        Args:
            doc: The compiled document.
            output_dir: Base output directory.

        Returns:
            List of paths that were written.
        """
        output_path = output_dir / f"{doc.uri}.md"

        # Ensure parent directories exist
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Write the compiled output
        output_path.write_text(doc.output, encoding="utf-8")

        return [output_path]
