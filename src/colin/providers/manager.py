"""Provider registry and lifecycle management."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime

from colin.api.project import ProjectConfig, ProviderInstanceConfig
from colin.providers.base import Provider
from colin.providers.context import ProviderContext
from colin.providers.namespace import Namespace, build_namespace

logger = logging.getLogger(__name__)

ProviderFactory = Callable[[ProviderInstanceConfig], Provider]

_PROVIDER_FACTORIES: dict[str, ProviderFactory] = {}


def register_provider_factory(provider_type: str, factory: ProviderFactory) -> None:
    """Register a factory for a provider type."""
    if provider_type in _PROVIDER_FACTORIES:
        logger.warning("Overwriting provider factory for %s", provider_type)
    _PROVIDER_FACTORIES[provider_type] = factory


def create_provider(config: ProviderInstanceConfig) -> Provider:
    """Create a provider instance from configuration."""
    if config.provider_type not in _PROVIDER_FACTORIES:
        available = ", ".join(sorted(_PROVIDER_FACTORIES)) or "(none)"
        raise ValueError(f"Unknown provider type '{config.provider_type}'. Available: {available}")
    provider = _PROVIDER_FACTORIES[config.provider_type](config)
    if config.scheme:
        provider.schemes = [config.scheme]
    return provider


def _register_builtin_factories() -> None:
    from colin.providers.mcp import create_mcp_provider

    if "mcp" not in _PROVIDER_FACTORIES:
        register_provider_factory("mcp", create_mcp_provider)


class ProviderInstanceEntry:
    """Provider instance wrapper for namespace construction."""

    def __init__(self, provider: Provider) -> None:
        self.provider = provider
        self.functions = provider.get_functions()


class ProviderTypeEntry:
    """Collection of instances for a provider type."""

    def __init__(self) -> None:
        self.default: ProviderInstanceEntry | None = None
        self.instances: dict[str, ProviderInstanceEntry] = {}


class ProviderRegistry:
    """Registry of provider types and instances."""

    def __init__(self) -> None:
        self._types: dict[str, ProviderTypeEntry] = {}

    def register(self, provider_type: str, instance: str | None, provider: Provider) -> None:
        entry = self._types.setdefault(provider_type, ProviderTypeEntry())
        instance_entry = ProviderInstanceEntry(provider)
        if instance is None:
            entry.default = instance_entry
        else:
            entry.instances[instance] = instance_entry

    def get_type(self, provider_type: str) -> ProviderTypeEntry:
        return self._types[provider_type]

    @property
    def types(self) -> dict[str, ProviderTypeEntry]:
        return self._types


class ProviderManager:
    """Manages provider lifecycle and namespace access."""

    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}
        self._registry = ProviderRegistry()

    def namespace(self, ctx: ProviderContext) -> Namespace:
        return build_namespace(ctx, self._registry)

    def register(self, provider: Provider, instance: str | None = None) -> None:
        """Register a provider for all its schemes."""
        for scheme in provider.schemes:
            self._providers[scheme] = provider
        namespace = provider.namespace or provider.schemes[0]
        self._registry.register(namespace, instance, provider)

    def get_provider(self, scheme: str) -> Provider:
        return self._providers[scheme]

    async def get_ref_last_updated(self, uri: str) -> datetime | None:
        """Get last update time for a URI without loading content.

        Parses the URI scheme and delegates to the appropriate provider's
        get_last_updated() method.

        Args:
            uri: Full URI (e.g., 'project://greeting.md', 'mcp.linear://?resource=...')

        Returns:
            Last update time, or None if unknown (treat as stale).
        """
        if "://" not in uri:
            # Schemaless - assume project://
            uri = f"project://{uri}"

        scheme = uri.split("://", 1)[0]

        try:
            provider = self.get_provider(scheme)
        except KeyError:
            # Unknown scheme - treat as stale
            return None

        return await provider.get_last_updated(uri)

    async def close(self) -> None:
        for provider in self._providers.values():
            close = getattr(provider, "close", None)
            if callable(close):
                await close()


@asynccontextmanager
async def create_provider_manager(config: ProjectConfig) -> AsyncIterator[ProviderManager]:
    """Create a provider manager for a project."""
    manager = ProviderManager()
    try:
        _register_builtin_factories()
        for instance in config.providers.values():
            provider = create_provider(instance)
            manager.register(provider, instance=instance.name)

        # Register builtin providers
        from colin.providers.http import HTTPProvider
        from colin.providers.llm import LLMProvider

        if "http" not in manager._registry.types:
            manager.register(HTTPProvider())

        if "llm" not in manager._registry.types:
            manager.register(LLMProvider())

        yield manager
    finally:
        await manager.close()
