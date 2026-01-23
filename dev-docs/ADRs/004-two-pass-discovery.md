# ADR 004: Two-Pass Discovery

**Status**: Accepted
**Date**: 2024-12-27

## Context

The original design said "graph is discovered at compile time by tracking which refs actually execute." This works for incremental recompilation (manifest stores previous refs), but creates a bootstrap problem on first compile:

1. We don't know the dependency graph yet
2. We can't compile in dependency order
3. If document A refs document B, but B hasn't been compiled, A fails

## Decision

Use two-pass discovery:

**Pass 1**: Parse all templates with Jinja AST to extract `ref()` calls without rendering:
```python
def extract_refs(template_source: str, env: Environment) -> list[str]:
    ast = env.parse(template_source)
    # Walk AST for Call nodes where func.name == 'ref'
    # Extract string literal arguments
    return refs
```

**Pass 2**: Compile in topological order using the discovered graph.

## Rationale

1. **Solves bootstrap**: First compile works without prior manifest
2. **Correct ordering**: Dependencies always compiled before dependents
3. **Minimal overhead**: AST parsing is fast, only done once per compile
4. **Better errors**: Can detect missing refs before compilation starts

## Limitations

- Only works for static refs like `ref('context/foo')`
- Dynamic refs like `ref(some_var)` can't be discovered statically
- Conditional refs (`{% if x %}{{ ref('a') }}{% endif %}`) may not match runtime

These are acceptable: dbt has the same limitations, and static refs are the 90% case.

## Consequences

- Need AST walking code in loader
- First compile is consistent with subsequent compiles
- Can warn about dynamic refs that can't be statically analyzed
