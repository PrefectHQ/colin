"""Markdown renderer."""

from colin.renders.base import Renderer


class MarkdownRenderer(Renderer):
    """Renderer for markdown output.

    Passthrough renderer - content is already markdown from templates.
    Uses base class render() which passes through content unchanged.
    """

    name: str = "markdown"
    extension: str = ".md"
