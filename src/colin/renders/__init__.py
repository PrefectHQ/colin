"""Renderers for transforming compiled content."""

from colin.providers.registry import get_renderer as get_renderer
from colin.providers.registry import register_renderer
from colin.renders.base import Renderer as Renderer
from colin.renders.json import JSONRenderer
from colin.renders.markdown import MarkdownRenderer
from colin.renders.yaml import YAMLRenderer


def register_default_renderers() -> None:
    """Register the built-in renderers.

    Called automatically on module load. Can be called again safely
    (will just overwrite with same instances).
    """
    register_renderer(MarkdownRenderer())
    register_renderer(JSONRenderer())
    register_renderer(YAMLRenderer())


# Register defaults when module is imported
register_default_renderers()
