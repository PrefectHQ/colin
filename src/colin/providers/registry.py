"""Provider registry for managing registered providers and renderers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from colin.providers.base import Provider
    from colin.providers.storage.base import Storage
    from colin.renders.base import Renderer

logger = logging.getLogger(__name__)

# Registered providers by namespace
_PROVIDERS: dict[str, Provider] = {}

# Registered renderers by name
_RENDERERS: dict[str, Renderer] = {}


def register_provider(provider: Provider) -> None:
    """Register a provider instance by its namespace.

    Args:
        provider: Provider instance with 'namespace' ClassVar.
    """
    namespace = provider.namespace
    if namespace is None:
        raise ValueError(f"Provider {type(provider).__name__} has no namespace")
    if namespace in _PROVIDERS:
        logger.warning(f"Overwriting provider for namespace: {namespace}")
    _PROVIDERS[namespace] = provider
    logger.debug(f"Registered provider: {namespace}")


def register_renderer(renderer: Renderer) -> None:
    """Register a renderer instance.

    Args:
        renderer: Renderer instance with a 'name' attribute.
    """
    # Renderer base class validates 'name' in __init_subclass__
    name = renderer.name
    if name in _RENDERERS:
        logger.warning(f"Overwriting renderer: {name}")
    _RENDERERS[name] = renderer
    logger.debug(f"Registered renderer: {name}")


def get_provider(namespace: str) -> Provider:
    """Get provider for a namespace.

    Args:
        namespace: Provider namespace (e.g., 's3', 'mcp', 'http').

    Returns:
        Provider instance.

    Raises:
        KeyError: If no provider for namespace.
    """
    if namespace not in _PROVIDERS:
        available = ", ".join(sorted(_PROVIDERS.keys())) or "(none)"
        raise KeyError(f"No provider for namespace: {namespace!r}. Available: {available}")
    return _PROVIDERS[namespace]


def get_storage(namespace: str) -> Storage:
    """Get storage for a namespace.

    Storage is a Provider that also supports write().

    Args:
        namespace: Provider namespace (e.g., 'file', 's3').

    Returns:
        Storage instance.

    Raises:
        KeyError: If no provider for namespace.
        TypeError: If provider is not a Storage.
    """
    from colin.providers.storage.base import Storage

    provider = get_provider(namespace)
    if not isinstance(provider, Storage):
        raise TypeError(f"Provider for {namespace!r} is not a Storage (cannot write)")
    return provider


def get_renderer(name: str) -> Renderer:
    """Get renderer by name.

    Args:
        name: Renderer name (e.g., 'json', 'markdown').

    Returns:
        Renderer instance.

    Raises:
        KeyError: If no renderer with name.
    """
    if name not in _RENDERERS:
        available = ", ".join(sorted(_RENDERERS.keys())) or "(none)"
        raise KeyError(f"Unknown renderer: {name!r}. Available: {available}")
    return _RENDERERS[name]


def list_providers() -> list[str]:
    """List all registered provider namespaces.

    Returns:
        List of namespace names.
    """
    return sorted(_PROVIDERS.keys())


def list_renderers() -> list[str]:
    """List all registered renderer names.

    Returns:
        List of renderer names.
    """
    return sorted(_RENDERERS.keys())


def clear_registry() -> None:
    """Clear all registered providers and renderers.

    Primarily for testing.
    """
    _PROVIDERS.clear()
    _RENDERERS.clear()
