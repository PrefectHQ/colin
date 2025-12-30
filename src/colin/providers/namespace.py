"""Provider namespace helpers for templates."""

from __future__ import annotations

from typing import TYPE_CHECKING

from colin.providers.context import ProviderContext

if TYPE_CHECKING:
    from colin.providers.manager import ProviderInstanceEntry, ProviderRegistry


class Namespace:
    """Dot-access wrapper for nested Namespace objects."""

    def __init__(self, mapping: dict[str, object], default_key: str = "__default__") -> None:
        self._mapping = mapping
        self._default_key = default_key

    def __getattr__(self, name: str) -> object:
        if name in self._mapping:
            return self._mapping[name]
        if self._default_key in self._mapping:
            default = self._mapping[self._default_key]
            try:
                return getattr(default, name)
            except AttributeError:
                pass
        raise AttributeError(f"No attribute '{name}'")

    def __getitem__(self, name: str) -> object:
        if name in self._mapping:
            return self._mapping[name]
        if name == "default" and self._default_key in self._mapping:
            return self._mapping[self._default_key]
        raise KeyError(f"No key '{name}'")


def build_namespace(ctx: ProviderContext, registry: ProviderRegistry) -> Namespace:
    """Build a provider namespace bound to a context."""
    types: dict[str, object] = {}
    for provider_type, entry in registry.types.items():
        type_map: dict[str, object] = {}
        for name, instance in entry.instances.items():
            type_map[name] = build_instance_namespace(instance, ctx)
        if entry.default:
            type_map["__default__"] = build_instance_namespace(entry.default, ctx)
        types[provider_type] = Namespace(type_map)
    return Namespace(types)


def build_instance_namespace(instance: ProviderInstanceEntry, ctx: ProviderContext) -> Namespace:
    """Build a namespace for a single provider instance."""
    funcs: dict[str, object] = {}
    for name, func in instance.functions.items():

        async def wrapper(*args: object, _func=func, _ctx=ctx, **kwargs: object) -> object:
            return await _func(_ctx, *args, **kwargs)

        funcs[name] = wrapper
    return Namespace(funcs)
