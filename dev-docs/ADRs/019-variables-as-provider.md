# ADR 019: Variables as a Provider

**Status**: Accepted
**Date**: 2026-01-04

## Context

Project variables (`--var`, `COLIN_VAR_*`) were being ignored for cached documents. The staleness check didn't consider variable values, so changing a variable wouldn't trigger recompilation.

We needed per-variable staleness tracking so only documents using changed variables would rebuild.

## Decision

Variables are implemented as a proper Provider (`VariableProvider`) with ref-based staleness tracking:

- `vars.foo` access in templates creates an implicit `Ref(provider="variable", args={"name": "foo"})`
- The ref version is a hash of the resolved value
- Staleness detection uses the existing ref mechanism

## Rationale

1. **Reuses existing machinery**: The ref/staleness system already handles per-dependency tracking
2. **Granular invalidation**: Only documents using a changed variable recompile
3. **Consistent model**: Variables work like any other provider dependency
4. **No special cases**: The staleness check doesn't need variable-specific logic

## Consequences

- `VarsProxy` wraps `VariableProvider` and creates refs on attribute access
- Variable values are hashed (not stored raw) in `ref_versions` for privacy
- The `secret` type was removed since values still appear in the manifest hash
