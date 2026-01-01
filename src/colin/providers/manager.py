"""Provider registry and lifecycle management."""

from __future__ import annotations

import importlib
import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime

from colin.api.project import ProjectConfig, ProviderInstanceConfig
from colin.providers.base import Provider
from colin.providers.context import ProviderContext
from colin.providers.http import HTTPProvider
from colin.providers.llm import LLMProvider
from colin.providers.mcp import MCPProvider
from colin.providers.namespace import Namespace, build_namespace

logger = logging.getLogger(__name__)

_PROVIDER_CLASSES: dict[str, type[Provider] | str] = {
    "http": HTTPProvider,
    "https": HTTPProvider,
    "llm": LLMProvider,
    "mcp": MCPProvider,
    "s3": "colin.providers.s3:S3Provider",  # Lazy import
}


def _get_provider_class(provider_type: str) -> type[Provider]:
    """Get provider class, handling lazy imports for optional deps."""
    if provider_type not in _PROVIDER_CLASSES:
        available = ", ".join(sorted(_PROVIDER_CLASSES)) or "(none)"
        raise ValueError(f"Unknown provider type '{provider_type}'. Available: {available}")

    cls = _PROVIDER_CLASSES[provider_type]

    if isinstance(cls, str):
        module_path, class_name = cls.rsplit(":", 1)
        module = importlib.import_module(module_path)  # Let ImportError bubble up
        cls = getattr(module, class_name)
        _PROVIDER_CLASSES[provider_type] = cls  # Cache for next time

    return cls


def create_provider(config: ProviderInstanceConfig) -> Provider:
    """Create a provider instance from configuration."""
    provider_cls = _get_provider_class(config.provider_type)
    provider = provider_cls.from_config(config.name, config.config)
    provider.schemes = config.get_schemes()
    return provider


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


@asynccontextmanager
async def create_provider_manager(config: ProjectConfig) -> AsyncIterator[ProviderManager]:
    """Create a provider manager for a project."""
    manager = ProviderManager()

    async with AsyncExitStack() as stack:
        for instance in config.providers.values():
            provider = create_provider(instance)
            manager.register(provider, instance=instance.name)

        # Register builtin providers if not configured
        if "http" not in manager._registry.types:
            manager.register(HTTPProvider())

        if "llm" not in manager._registry.types:
            manager.register(LLMProvider())

        # Enter lifespans for unique provider instances
        seen: set[int] = set()
        for provider in manager._providers.values():
            if id(provider) not in seen:
                seen.add(id(provider))
                await stack.enter_async_context(provider.lifespan())

        yield manager
