"""Provider namespace helpers for templates."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from colin.providers.manager import ProviderInstanceEntry, ProviderRegistry


class Namespace:
    """Dot-access wrapper for nested Namespace objects."""

    def __init__(
        self,
        mapping: dict[str, object],
        default_key: str = "__default__",
        name: str | None = None,
    ) -> None:
        self._mapping = mapping
        self._default_key = default_key
        self._name = name

    def __getattr__(self, name: str) -> object:
        if name in self._mapping:
            value = self._mapping[name]
            # Propagate the path name to child namespaces
            if isinstance(value, Namespace) and value._name is None:
                value._name = f"{self._name}.{name}" if self._name else name
            return value
        if self._default_key in self._mapping:
            default = self._mapping[self._default_key]
            try:
                return getattr(default, name)
            except AttributeError:
                pass
        display_name = f"'{self._name}'" if self._name else "namespace"
        raise AttributeError(f"{display_name} has no attribute '{name}'")

    def __getitem__(self, name: str) -> object:
        if name in self._mapping:
            return self._mapping[name]
        if name == "default" and self._default_key in self._mapping:
            return self._mapping[self._default_key]
        raise KeyError(f"No key '{name}'")


class MCPNamespace(Namespace):
    """Specialized namespace for MCP provider with list_servers() support.

    Template usage:
        {% set servers = colin.mcp.list_servers() %}
        {% for name in servers %}
            {% set server = colin.mcp[name] %}
            ...
        {% endfor %}
    """

    def __init__(
        self,
        mapping: dict[str, object],
        default_key: str = "__default__",
        name: str | None = None,
    ) -> None:
        super().__init__(mapping, default_key, name)
        # Cache server names (exclude internal keys)
        self._server_names = sorted(k for k in mapping if not k.startswith("_"))

    def list_servers(self) -> list[str]:
        """Return names of all configured MCP servers.

        Returns:
            List of server names (sorted alphabetically).
        """
        return self._server_names

    def __getattr__(self, name: str) -> object:
        # Make list_servers available as an attribute
        if name == "list_servers":
            return self.list_servers
        return super().__getattr__(name)


def build_namespace(registry: ProviderRegistry) -> Namespace:
    """Build a provider namespace for templates."""
    types: dict[str, object] = {}
    for provider_type, entry in registry.types.items():
        type_map: dict[str, object] = {}
        for name, instance in entry.instances.items():
            type_map[name] = build_instance_namespace(instance, f"{provider_type}.{name}")
        if entry.default:
            type_map["__default__"] = build_instance_namespace(entry.default, provider_type)

        # Use MCPNamespace for MCP provider to enable list_servers()
        if provider_type == "mcp":
            types[provider_type] = MCPNamespace(type_map, name=provider_type)
        else:
            types[provider_type] = Namespace(type_map, name=provider_type)
    return Namespace(types, name="colin")


def build_instance_namespace(instance: ProviderInstanceEntry, name: str) -> Namespace:
    """Build a namespace for a single provider instance."""
    funcs: dict[str, object] = {}
    for func_name, func in instance.functions.items():
        # Functions are called directly - no ctx injection needed
        # Functions that need context use get_compile_context()
        funcs[func_name] = func
    return Namespace(funcs, name=name)
