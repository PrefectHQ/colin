# ADR 020: Strict Static Compilation Model

**Status**: Accepted
**Date**: 2025-01-05

## Context

Colin supports dynamic refs where the target is determined at runtime:

```jinja
{{ ref(mcp.github.resource(uri)) }}     # External provider
{{ ref(s3.get("bucket/" + key)) }}      # Computed path
```

This creates a challenge: how do we determine compilation order when refs can be computed at runtime?

The core tension: **ordering** (what order to compile documents) vs **staleness** (what dependencies to check for changes).

## Decision

### Two-source model: ordering vs staleness

**Ordering** determines compilation sequence:
- Source: Static AST refs + `depends_on` frontmatter hints
- NOT from manifest (empirical refs from previous runs)
- Consistent behavior regardless of manifest state

**Staleness** determines when to rebuild:
- Source: Empirical refs from manifest (what was actually used last run)
- Includes dynamic refs that were resolved at runtime

### Strict compilation with `depends_on` hints

Documents must declare dependencies explicitly when refs can't be statically extracted:

```yaml
---
colin:
  depends_on:
    - generator.md
    - data-source.md
---
```

The `depends_on` field:
- Adds edges to the dependency graph for compilation ordering
- Does NOT affect staleness checking (that uses manifest empirical refs)
- Required for dynamic project refs like `ref(variable)` or `{% file %}` outputs

### `ref()` validation with `allow_stale` escape hatch

By default, `ref()` for project documents requires the target to be compiled in the current run:

```jinja
{{ ref("other-doc") }}                    # Fails if not compiled first
{{ ref("other-doc", allow_stale=True) }}  # Accepts stale data, returns None if never compiled
```

When a project ref target hasn't been compiled:
- **allow_stale=False (default)**: Raises `RefNotCompiledError` with guidance
- **allow_stale=True**: Returns stale data from storage, or `None` if never compiled

External refs (MCP, S3, HTTP) don't require `allow_stale`—they're always fetched directly.

### Cycles are illegal

Dependency cycles are compile-time errors:

```
Cycle detected: A → B → C → A
Use allow_stale=True on one ref to break the cycle.
```

To break a cycle, use `allow_stale=True` on one side—that document accepts stale data, removing the hard dependency.

### Error message guidance

`RefNotCompiledError` provides actionable guidance:

```
ref('other-doc') failed - document not compiled.
Add 'depends_on: [other-doc]' to ensure compilation order,
or use ref('other-doc', allow_stale=True) to accept stale/missing data.
```

## Rationale

1. **Predictable ordering**: Using only static sources (AST + hints) ensures consistent compilation order across runs, regardless of manifest state
2. **Dynamic refs are first-class**: External provider refs like `ref(mcp.resource())` work naturally—they don't need ordering hints
3. **Explicit over implicit**: Users declare dependencies they know about; the system doesn't guess from runtime behavior
4. **Graceful degradation**: `allow_stale` provides an escape hatch for cycles and cases where stale data is acceptable
5. **Clear separation**: Ordering (when to compile) is distinct from staleness (when to rebuild)

## Consequences

- `depends_on` frontmatter field for explicit dependency hints
- `ref()` raises `RefNotCompiledError` when target not compiled (project refs only)
- `allow_stale=True` parameter accepts stale/missing data
- `CyclicDependencyError` shows actual cycle path with resolution guidance
- External refs (MCP, S3, etc.) unchanged—always allowed
- Manifest empirical refs used only for staleness detection, not ordering

## Alternatives Considered

1. **Lazy compilation**: Compile documents on-demand when ref'd. Rejected—requires solving cycle detection at runtime, complex state management, unpredictable compilation order.

2. **Use manifest for ordering**: Build graph from empirical refs. Rejected—behavior would change based on manifest state (different on fresh clone vs incremental build).

3. **Allow cycles with resolution heuristics**: Pick arbitrary order for cycles. Rejected—unpredictable behavior, hard to debug.

4. **Require all refs to be static**: Only allow string literals in ref(). Rejected—dynamic refs to external providers are a core use case.
