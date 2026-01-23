# ADR 003: Async-First Design

**Status**: Accepted
**Date**: 2024-12-27

## Context

Colin makes LLM calls which are I/O-bound operations. We need to decide whether to use synchronous or asynchronous programming throughout the codebase.

## Decision

Colin is async-first:
- Jinja environment uses `enable_async=True`
- All plugin methods are `async def`
- Template rendering uses `render_async()`
- CLI runs the async event loop at the top level

## Rationale

1. **LLM calls are I/O-bound**: Waiting for LLM responses is the primary bottleneck
2. **Jinja supports it**: `enable_async=True` is a first-class feature
3. **Future parallelization**: Async enables running multiple LLM calls concurrently
4. **MCP is async**: Future MCP integration uses async protocols
5. **Modern Python**: Async is the standard for I/O-bound work

## Consequences

- All code paths must be async-aware
- Template functions like `ref()` and filters like `| extract()` are async
- Tests use `pytest-asyncio` with `asyncio_mode = "auto"`
- Slightly more complex than sync, but worth it for scalability

## Implementation Notes

Jinja async mode:
```python
env = Environment(enable_async=True)
result = await template.render_async()
```

The `caller()` function in block extensions returns a coroutine that must be awaited.
