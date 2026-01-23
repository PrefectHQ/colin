"""Provider registry and lifecycle management."""

from __future__ import annotations

import importlib
import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from colin.api.project import ProjectConfig, ProviderInstanceConfig
from colin.compiler.namespace import Namespace, build_namespace
from colin.providers.base import Provider
from colin.providers.file import FileProvider
from colin.providers.http import HTTPProvider
from colin.providers.llm import LLMProvider

logger = logging.getLogger(__name__)

_PROVIDER_CLASSES: dict[str, type[Provider] | str] = {
    "file": FileProvider,
    "github": "colin.providers.github:GitHubProvider",  # Lazy import
    "http": HTTPProvider,
    "linear": "colin.providers.linear:LinearProvider",  # Lazy import
    "llm": LLMProvider,
    "mcp": "colin.providers.mcp:MCPProvider",  # Lazy import to avoid circular dependency
    "notion": "colin.providers.notion:NotionProvider",  # Lazy import
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
    return provider_cls.from_config(config.name, config.config)


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

    def get_provider(self, provider_type: str, instance: str | None = None) -> Provider | None:
        """Get a provider by type and optional instance name."""
        if provider_type not in self._types:
            return None
        entry = self._types[provider_type]
        if instance:
            inst_entry = entry.instances.get(instance)
            return inst_entry.provider if inst_entry else None
        return entry.default.provider if entry.default else None

    @property
    def types(self) -> dict[str, ProviderTypeEntry]:
        return self._types


class ProviderManager:
    """Manages provider lifecycle and namespace access."""

    def __init__(self) -> None:
        self._registry = ProviderRegistry()
        self._all_providers: list[Provider] = []
        self._config_hashes: dict[tuple[str, str], str] = {}  # (type, connection) -> hash

    def namespace(self) -> Namespace:
        return build_namespace(self._registry)

    def register(
        self,
        provider: Provider,
        instance: str | None = None,
        config_hash: str | None = None,
    ) -> None:
        """Register a provider.

        Args:
            provider: The provider instance.
            instance: Connection/instance name (e.g., 'prod' for s3.prod).
            config_hash: Hash of provider config for staleness tracking.
        """
        namespace = provider.namespace
        if namespace is None:
            raise ValueError(f"Provider {type(provider).__name__} has no namespace")
        self._registry.register(namespace, instance, provider)
        self._all_providers.append(provider)

        # Store config hash for staleness tracking
        if config_hash is not None:
            key = (namespace, instance or "")
            self._config_hashes[key] = config_hash

    def get_provider(self, provider_type: str, instance: str | None = None) -> Provider | None:
        """Get a provider by type and optional instance name."""
        return self._registry.get_provider(provider_type, instance)

    def get_config_hash(self, provider_type: str, connection: str) -> str | None:
        """Get config hash for a provider connection.

        Args:
            provider_type: Provider type (e.g., 'llm', 's3').
            connection: Connection name (empty string for default).

        Returns:
            Config hash if registered, None otherwise.
        """
        return self._config_hashes.get((provider_type, connection))


@asynccontextmanager
async def create_provider_manager(config: ProjectConfig) -> AsyncIterator[ProviderManager]:
    """Create a provider manager for a project."""
    manager = ProviderManager()

    async with AsyncExitStack() as stack:
        for inst_config in config.providers.values():
            provider = create_provider(inst_config)
            manager.register(
                provider,
                instance=inst_config.name,
                config_hash=inst_config.config_hash,
            )

        # Register builtin providers if not configured
        if "file" not in manager._registry.types:
            manager.register(FileProvider())

        if "github" not in manager._registry.types:
            github_cls = _get_provider_class("github")
            manager.register(github_cls())

        if "http" not in manager._registry.types:
            manager.register(HTTPProvider())

        if "llm" not in manager._registry.types:
            manager.register(LLMProvider())

        # Enter lifespans for all providers
        for provider in manager._all_providers:
            await stack.enter_async_context(provider.lifespan())

        yield manager
