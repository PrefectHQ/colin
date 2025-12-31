"""Provider function caching with @cached decorator."""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Callable
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from typing import TYPE_CHECKING, Any

import pydantic_core

from colin.models import CacheEntry

if TYPE_CHECKING:
    from colin.compiler.context import CompileContext

# Context variable for current compilation
_compile_context: ContextVar[CompileContext | None] = ContextVar("compile_context", default=None)


def get_compile_context() -> CompileContext | None:
    """Get current compile context, or None if not in compilation."""
    return _compile_context.get()


def set_compile_context(ctx: CompileContext | None) -> None:
    """Set the current compile context."""
    _compile_context.set(ctx)


def _serialize_value(value: object) -> str:
    """Serialize a value for hashing.

    Uses pydantic_core.to_jsonable_python() to handle complex types (dataclasses,
    pydantic models, etc.), then json.dumps with sort_keys for deterministic output.

    Note: pydantic_core.to_json() is faster but lacks sort_keys parameter,
    which is required for deterministic hashing.
    """
    jsonable = pydantic_core.to_jsonable_python(value, fallback=str)
    return json.dumps(jsonable, sort_keys=True)


def hash_args(
    args: tuple[Any, ...], kwargs: dict[str, Any], exclude_args: set[str] | None = None
) -> str:
    """Hash function arguments for cache key.

    Args:
        args: Positional arguments.
        kwargs: Keyword arguments.
        exclude_args: Argument names to exclude from hash.

    Returns:
        16-character hash string.
    """
    exclude_args = exclude_args or set()
    parts = [_serialize_value(arg) for arg in args]
    for key in sorted(kwargs):
        if key not in exclude_args:
            parts.append(f"{key}={_serialize_value(kwargs[key])}")
    combined = "|".join(parts)
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


def hash_args_for_func(
    func: Callable[..., Any],
    bound_args: dict[str, Any],
    exclude_args: set[str] | None = None,
) -> str:
    """Hash function arguments using parameter names.

    Args:
        func: The function (unused, kept for API consistency).
        bound_args: Arguments bound to parameter names.
        exclude_args: Argument names to exclude from hash.

    Returns:
        16-character hash string.
    """
    exclude_args = exclude_args or set()

    parts = []
    for name in sorted(bound_args.keys()):
        if name not in exclude_args and not name.startswith("_"):
            parts.append(f"{name}={_serialize_value(bound_args[name])}")

    combined = "|".join(parts)
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


def cached(
    key: str,
    exclude_args: set[str] | None = None,
):
    """Decorator to cache provider function results.

    Args:
        key: Cache key prefix (e.g., "llm.extract").
        exclude_args: Argument names to exclude from hash.

    Call-time overrides (passed as kwargs):
        _cache_id: Custom cache ID (skips hash, uses this directly).
        _cache: Set to False to bypass cache entirely.
    """

    def decorator(func):
        sig = inspect.signature(func)

        @wraps(func)
        async def wrapper(
            self,
            ctx,
            *args,
            _cache_id: str | None = None,
            _cache: bool = True,
            **kwargs,
        ):
            compile_ctx = get_compile_context()

            # Skip cache if disabled or not in compilation
            if not _cache or compile_ctx is None:
                return await func(self, ctx, *args, **kwargs)

            # Build cache key - only compute hash if no manual _cache_id
            if _cache_id:
                cache_key = f"{key}:{_cache_id}"
            else:
                bound = sig.bind(self, ctx, *args, **kwargs)
                bound.apply_defaults()
                bound_args = {k: v for k, v in bound.arguments.items() if k not in ("self", "ctx")}
                cache_key = f"{key}:{hash_args_for_func(func, bound_args, exclude_args)}"

            # Check cache
            cached_entry = compile_ctx.manifest.cache.get(cache_key)
            if cached_entry:
                return json.loads(cached_entry.output)

            # Cache miss - execute function (exceptions propagate, not cached)
            result = await func(self, ctx, *args, **kwargs)

            # Store in cache
            compile_ctx.manifest.cache[cache_key] = CacheEntry(
                cache_key=cache_key,
                output=json.dumps(result),
                created_at=datetime.now(timezone.utc),
            )

            return result

        return wrapper

    return decorator
