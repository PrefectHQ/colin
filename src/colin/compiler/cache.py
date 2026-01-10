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

# Context variable for tracking used cache keys (for pruning unused entries)
_used_cache_keys: ContextVar[set[str] | None] = ContextVar("used_cache_keys", default=None)


def get_compile_context() -> CompileContext | None:
    """Get current compile context, or None if not in compilation."""
    return _compile_context.get()


def set_compile_context(ctx: CompileContext | None) -> None:
    """Set the current compile context."""
    _compile_context.set(ctx)


def get_used_cache_keys() -> set[str] | None:
    """Get the set of cache keys used in current compilation."""
    return _used_cache_keys.get()


def set_used_cache_keys(keys: set[str] | None) -> None:
    """Set the used cache keys set for tracking."""
    _used_cache_keys.set(keys)


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
    detail_arg: str | None = None,
):
    """Decorator to cache provider function results.

    Args:
        key: Cache key prefix (e.g., "llm.extract").
        exclude_args: Argument names to exclude from hash.
        detail_arg: Argument name to use for state tracking detail (e.g., "prompt").

    Call-time overrides (passed as kwargs):
        _position_id: Position-based ID for document-scoped caching. When provided,
            cache key includes position_id + input_hash for per-call uniqueness.
            Format: key:doc_uri:position_id:input_hash:config_hash
        _cache: Set to False to bypass cache entirely.

    Provider config hashing:
        If `self` has a `_config_hash` attribute, it will be included in the cache key.
        This ensures provider config changes invalidate cached results.

    Note on _position_id:
        The decorator extracts _position_id from kwargs for cache key computation,
        but does NOT strip it. Functions can declare _position_id as a parameter
        if they need it for previous_output lookup.
    """

    def decorator(func):
        sig = inspect.signature(func)

        @wraps(func)
        async def wrapper(
            self,
            *args,
            _position_id: str | None = None,
            _cache: bool = True,
            **kwargs,
        ):
            compile_ctx = get_compile_context()

            # Skip cache if disabled or not in compilation
            if not _cache or compile_ctx is None:
                # Pass _position_id if the function accepts it
                func_params = sig.parameters
                if "_position_id" in func_params:
                    return await func(self, *args, _position_id=_position_id, **kwargs)
                return await func(self, *args, **kwargs)

            # Provider config hash - included in all cache keys
            config_hash = getattr(self, "_config_hash", None)
            doc_uri = compile_ctx.document_uri

            # Build cache key - always includes input hash for correctness
            bound = sig.bind(self, *args, **kwargs)
            bound.apply_defaults()
            bound_args = {k: v for k, v in bound.arguments.items() if k != "self"}
            input_hash = hash_args_for_func(func, bound_args, exclude_args)

            if _position_id:
                # Document-scoped cache key when using _position_id
                # Includes input_hash to handle loops correctly (each iteration unique)
                # Format: key:doc_uri:position_id:input_hash:config_hash
                parts = [key, doc_uri, _position_id, input_hash]
                if config_hash:
                    parts.append(config_hash)
                cache_key = ":".join(parts)
            else:
                # Hash-based cache key (global, shared across docs with same inputs)
                # Include provider config hash if available
                if config_hash:
                    bound_args["provider_config"] = config_hash
                    input_hash = hash_args_for_func(func, bound_args, exclude_args)

                cache_key = f"{key}:{input_hash}"

            # Track this cache key as used (for pruning unused entries)
            used_keys = get_used_cache_keys()
            if used_keys is not None:
                used_keys.add(cache_key)

            # Check cache
            cached_entry = compile_ctx.manifest.cache.get(cache_key)
            if cached_entry:
                # Track cache hit in state for UI display
                doc_state = compile_ctx.doc_state
                if doc_state:
                    # Get detail from args if specified
                    detail = None
                    if detail_arg:
                        bound = sig.bind(self, *args, **kwargs)
                        bound.apply_defaults()
                        detail_val = bound.arguments.get(detail_arg, "")
                        if detail_val:
                            # Truncate long details
                            detail_str = str(detail_val)
                            if len(detail_str) > 30:
                                detail_str = detail_str[:27] + "..."
                            detail = detail_str
                    op = doc_state.child("llm", detail=detail)
                    op.mark_cached()
                return json.loads(cached_entry.output)

            # Cache miss - execute function (exceptions propagate, not cached)
            # Pass _position_id if the function accepts it
            func_params = sig.parameters
            if "_position_id" in func_params:
                result = await func(self, *args, _position_id=_position_id, **kwargs)
            else:
                result = await func(self, *args, **kwargs)

            # Store in cache
            compile_ctx.manifest.cache[cache_key] = CacheEntry(
                cache_key=cache_key,
                output=json.dumps(result),
                created_at=datetime.now(timezone.utc),
            )

            return result

        return wrapper

    return decorator
