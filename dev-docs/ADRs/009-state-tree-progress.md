# ADR 009: Tree-based State for Progress Reporting

**Status**: Accepted
**Date**: 2024-12-27

## Context

The CLI needs to show progress during compilation:
- Which files are being processed
- What operations are running (LLM calls, extracts, refs, etc.)
- Support for future parallel execution of independent files
- Nested operations (e.g., extract filter contains an LLM call)

## Decision

Use a tree of mutable state objects that the compiler updates and the CLI reads.

```python
@dataclass
class OperationState:
    name: str
    status: Status  # pending, processing, done, failed
    detail: str | None
    parent: OperationState | None
    children: list[OperationState]

    def child(self, name: str) -> OperationState:
        """Create child with mutual attachment."""
        child = OperationState(name=name, parent=self)
        self.children.append(child)
        return child
```

Operations self-register by calling `parent.child()` and self-complete by calling `state.done()`.

## Alternatives Considered

1. **Event-based (start/end pairs)**: Requires matching start/end events, complex state reconstruction, error-prone for parallel execution
2. **Polling**: Doesn't fit async model well
3. **Callback per operation type**: Lots of callback parameters, not extensible to new operation types

## Rationale

1. **Simpler mental model**: State is always consistent, no event matching
2. **Parallel-friendly**: Multiple active operations are just tree nodes
3. **Generalizes**: Works for any operation type (LLM, extract, ref, MCP, future ops)
4. **Testable**: Assert on state at any point, not event sequences

## Consequences

- Tighter coupling between compiler and state structure
- Single consumer model (CLI reads state)
- CLI rendering is simple: walk tree, show non-done nodes
- Easy to add verbosity levels (show completed ops, more nesting)
