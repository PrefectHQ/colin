"""Jinja environment setup for Colin."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jinja2 import Environment

from colin.compiler.extensions.filters import create_llm_classify_filter, create_llm_extract_filter
from colin.compiler.extensions.item_block import ItemBlockExtension
from colin.compiler.extensions.llm_block import LLMBlockExtension
from colin.compiler.extensions.section_block import SectionBlockExtension

if TYPE_CHECKING:
    from colin.compiler.context import CompileContext
    from colin.providers.manager import ProviderManager


def create_jinja_environment() -> Environment:
    """Create an async-enabled Jinja environment with Colin extensions.

    Returns:
        Configured Jinja Environment.
    """
    env = Environment(
        enable_async=True,
        extensions=[LLMBlockExtension, ItemBlockExtension, SectionBlockExtension],
        # Don't auto-escape for markdown output
        autoescape=False,
    )
    return env


def bind_context_to_environment(
    env: Environment,
    context: CompileContext,
    provider_manager: ProviderManager,
) -> Environment:
    """Bind compile context functions to the environment.

    This adds the ref() function and LLM filters, and attaches
    the context so the LLM block extension can access it.

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

    # Providers namespace - exposed as `colin.*` in templates
    colin = provider_manager.namespace()
    env.globals["colin"] = colin

    # Attach llm namespace for LLM block extension
    env.llm_namespace = colin.llm  # type: ignore[attr-defined]

    # LLM filters (pipe syntax: content | llm_extract('prompt'))
    env.filters["llm_extract"] = create_llm_extract_filter(colin.llm)
    env.filters["llm_classify"] = create_llm_classify_filter(colin.llm)

    return env
