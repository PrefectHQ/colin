"""Jinja environment setup for Colin."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jinja2 import Environment

from colin.compiler.extensions.filters import create_extract_filter
from colin.compiler.extensions.llm_block import LLMBlockExtension

if TYPE_CHECKING:
    from colin.compiler.context import CompileContext


def create_jinja_environment() -> Environment:
    """Create an async-enabled Jinja environment with Colin extensions.

    Returns:
        Configured Jinja Environment.
    """
    env = Environment(
        enable_async=True,
        extensions=[LLMBlockExtension],
        # Don't auto-escape for markdown output
        autoescape=False,
    )
    return env


def bind_context_to_environment(
    env: Environment,
    context: CompileContext,
) -> Environment:
    """Bind compile context functions to the environment.

    This adds the ref() function and extract filter, and attaches
    the context so the LLM block extension can access it.

    Args:
        env: The Jinja environment.
        context: The compile context.

    Returns:
        The environment with context bound.
    """
    # Attach context for extension access
    env.compile_context = context  # type: ignore[attr-defined]

    # Core functions
    env.globals["ref"] = context.ref
    env.globals["mcp_resource"] = context.mcp_resource

    # LLM filters
    env.filters["extract"] = create_extract_filter(context)

    return env
