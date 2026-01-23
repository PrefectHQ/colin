"""Jinja environment setup for Colin."""

from __future__ import annotations

import functools
import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from jinja2 import Environment

from colin.compiler.extensions.defer_block import DeferBlockExtension
from colin.compiler.extensions.file_block import FileBlockExtension
from colin.compiler.extensions.filters import create_llm_classify_filter, create_llm_extract_filter
from colin.compiler.extensions.item_block import ItemBlockExtension
from colin.compiler.extensions.llm_block import LLMBlockExtension
from colin.compiler.extensions.section_block import SectionBlockExtension
from colin.compiler.namespace import Namespace
from colin.models import Ref
from colin.providers.variable import _hash_value

if TYPE_CHECKING:
    from colin.compiler.context import CompileContext
    from colin.providers.manager import ProviderManager
    from colin.providers.variable import VariableProvider


class VarsProxy:
    """Proxy that creates refs when variables are accessed.

    Wraps a VariableProvider and tracks each variable access as a ref
    in the compile context for per-variable staleness detection.
    """

    def __init__(self, provider: VariableProvider, context: CompileContext) -> None:
        object.__setattr__(self, "_provider", provider)
        object.__setattr__(self, "_context", context)

    def __getattr__(self, name: str) -> Any:
        """Access a variable, creating a ref for staleness tracking."""
        provider: VariableProvider = object.__getattribute__(self, "_provider")
        context: CompileContext = object.__getattribute__(self, "_context")

        # Get the value from the provider
        value = provider.get(name)

        # Create and track ref with hashed version (not raw value)
        ref = Ref(provider="variable", connection="", method="get", args={"name": name})
        version = _hash_value(value)

        context.refs.append(ref)
        context.ref_versions[ref.key()] = version

        return value


def _wrap_provider_functions(
    namespace: Namespace,
    context: CompileContext,
    provider_manager: ProviderManager,
) -> None:
    """Wrap all provider functions to track config on first use.

    Walks the namespace structure and wraps each function to track provider
    config when the function is called. This enables staleness detection when
    provider configuration changes in colin.toml.

    Args:
        namespace: The top-level colin namespace.
        context: Compile context for tracking refs.
        provider_manager: Provider manager with config hashes.
    """

    def wrap_function(
        func: Callable[..., Any],
        provider_type: str,
        connection: str,
    ) -> Callable[..., Any]:
        """Wrap a single function to track config on first call."""

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Track provider config on first use
            # Use empty hash for builtins without explicit config
            config_hash = provider_manager.get_config_hash(provider_type, connection)
            if config_hash is None:
                from colin.providers.base import BUILTIN_CONFIG_HASH

                config_hash = BUILTIN_CONFIG_HASH
            context.track_provider_config(provider_type, connection, config_hash)
            return await func(*args, **kwargs)

        return wrapper

    # Walk the namespace structure: colin.{provider_type}.{connection}.{function}
    for provider_type, type_namespace in namespace._mapping.items():
        if not isinstance(type_namespace, Namespace):
            continue

        # Walk instances (including __default__)
        for connection_key, instance_namespace in type_namespace._mapping.items():
            if not isinstance(instance_namespace, Namespace):
                continue

            # Determine actual connection name (empty for default)
            connection = "" if connection_key == "__default__" else connection_key

            # Wrap all functions in this instance
            for func_name, func in list(instance_namespace._mapping.items()):
                if callable(func):
                    instance_namespace._mapping[func_name] = wrap_function(
                        func, provider_type, connection
                    )


def from_json(value: str) -> Any:
    """Parse JSON string to Python object.

    Usage in templates:
        {{ resource.content | from_json }}
        {% set data = resource.content | from_json %}
        {{ data.field }}
    """
    return json.loads(value)


def create_jinja_environment() -> Environment:
    """Create an async-enabled Jinja environment with Colin extensions.

    Returns:
        Configured Jinja Environment.
    """
    env = Environment(
        enable_async=True,
        extensions=[
            LLMBlockExtension,
            ItemBlockExtension,
            SectionBlockExtension,
            DeferBlockExtension,
            FileBlockExtension,
        ],
        # Don't auto-escape for markdown output
        autoescape=False,
    )
    # Utility filters
    env.filters["from_json"] = from_json
    return env


def bind_context_to_environment(
    env: Environment,
    context: CompileContext,
    provider_manager: ProviderManager,
) -> Environment:
    """Bind compile context functions to the environment.

    This adds the ref() function, LLM filters, project variables,
    and attaches the context so the LLM block extension can access it.

    Args:
        env: The Jinja environment.
        context: The compile context.
        provider_manager: Provider manager for accessing providers.

    Returns:
        The environment with context bound.
    """
    # Attach context for extension access
    env.compile_context = context  # type: ignore[attr-defined]

    # Core functions
    env.globals["ref"] = context.ref
    env.globals["output"] = context.output

    # Providers namespace - exposed as `colin.*` in templates
    colin = provider_manager.namespace()

    # Wrap provider functions to track config on first use
    _wrap_provider_functions(colin, context, provider_manager)

    env.globals["colin"] = colin

    # Project variables - exposed as `vars.*` in templates with ref tracking
    variable_provider = provider_manager.get_provider("variable")
    if variable_provider is not None:
        env.globals["vars"] = VarsProxy(variable_provider, context)  # type: ignore[arg-type]
    else:
        env.globals["vars"] = {}

    # Attach llm namespace for LLM block extension
    env.llm_namespace = colin.llm  # type: ignore[attr-defined]

    # LLM filters (pipe syntax: content | llm_extract('prompt'))
    env.filters["llm_extract"] = create_llm_extract_filter(colin.llm)
    env.filters["llm_classify"] = create_llm_classify_filter(colin.llm)

    return env
