# ADR 001: MVP Scope

**Status**: Accepted
**Date**: 2024-12-27

## Context

Colin is an ambitious project with many potential features. We need to define a minimal viable product that validates the core value proposition without overbuilding.

## Decision

### In MVP

- `ref()` for local `.colin` files, returning structured `RefResult`
- `{% llm %}` block with optional `id` parameter (stub implementation)
- `| extract()` filter with optional `id` parameter (stub implementation)
- LLM call caching (auto ID + manual ID support)
- JSON manifest with Pydantic models
- Change detection via source hashing
- Topological compilation order (DAG)
- `colin compile` command
- Output to `dist/` directory as markdown

### Out of MVP

- MCP integration (`mcp()` function, `mcp_tool()`)
- Remote `colin://` refs
- `{% pin %}` blocks (complex LLM reliability)
- Watch mode (`colin watch`)
- Skills output format
- `compiled.previous` (whole document's prior output)
- `| summarize()`, `| translate()` filters
- `| new()`, `| changed()`, `| diff()` filters
- Actual LLM calls (stub only)
- Parallelization of LLM calls within a document
- `colin.yaml` config file (use sensible defaults)
- TransformPlugin (filters are hardcoded)

## Rationale

The core value proposition is:
1. `ref()` for dependency tracking
2. LLM transformations with caching
3. Incremental compilation

Everything else is enhancement. By focusing on local files and stub LLM, we can validate the compile loop and caching patterns before adding complexity.

## Consequences

- MVP can be built and tested quickly
- Real LLM integration will require configuration work later
- Some features from the design doc are deferred
- Users can still get value from the core compile/ref/cache pattern
