# ADR 022: Output Function for Self-Referencing

**Status**: Accepted
**Date**: 2026-01-22

## Context

Documents needed a way to access their own previous output to support workflows where:
1. Users manually edit published output files and want those edits preserved on recompilation
2. LLM blocks need to make targeted edits rather than rewriting from scratch
3. Documents evolve over time rather than being regenerated completely

The existing `previous_rendered` variable in defer blocks read from Colin's artifact cache, which didn't capture manual edits to published files. It was also only available in defer blocks, limiting its usefulness.

## Decision

Introduce a unified `output()` function available everywhere in templates:

```jinja
{{ output() }}              # reads from published output (output/)
{{ output(cached=True) }}   # reads from artifact cache (.colin/compiled/)
```

Key behaviors:
- Returns `RenderedOutput` with `.content` and `.sections`, or `None` if not found
- Does NOT contribute to staleness tracking (avoids infinite loops)
- Works in all template contexts, not just defer blocks
- `output()` falls back to cached if published file doesn't exist
- `previous_rendered` is removed (breaking change)

### Implementation Details

The function reads from the document's output path as recorded in the manifest:

1. **`output()`** (default): Reads from `{output_path}/{doc.output_path}`. If the published file doesn't exist (first compile, private doc, deleted file), falls back to the cached version.

2. **`output(cached=True)`**: Reads from `.colin/compiled/{doc.output_path}`. No fallback—returns `None` if not found.

This requires that the document has been compiled at least once (so the manifest has `output_path`). On first compile, both return `None`.

## Human-in-the-Loop Workflow

The core use case is enabling collaboration between Colin and humans on the same document:

```
┌─────────────────────────────────────────────────────────────┐
│  1. colin run                                               │
│     └─> Compiles model → writes to output/doc.md           │
│                                                             │
│  2. User edits output/doc.md directly                       │
│     └─> Fixes typo, adds paragraph, adjusts wording        │
│                                                             │
│  3. colin run (triggered by source change)                  │
│     └─> Template calls output() → sees user's edits        │
│     └─> LLM makes targeted updates, preserving edits       │
│     └─> Writes new output that includes user changes       │
└─────────────────────────────────────────────────────────────┘
```

This works because `output()` reads the actual file on disk, not what's recorded in the manifest. User edits are captured without any manifest update—Colin sees the current filesystem state.

### Example: Docs That Evolve

```jinja
---
name: Feature Documentation
---
{% set current = output() %}
{% if current %}
{# Preserve existing content, make targeted updates #}
{% llm %}
Here is the current documentation:
{{ current.content }}

Here is the latest source code:
{{ ref(file.get("src/feature.py")) }}

Update the documentation to reflect any changes in the source.
Make minimal edits. Preserve existing structure and wording.
{% endllm %}
{% else %}
{# First compile: generate from scratch #}
{% llm %}
Write documentation for this feature:
{{ ref(file.get("src/feature.py")) }}
{% endllm %}
{% endif %}
```

On subsequent compiles, user edits to the output file are loaded, passed to the LLM, and preserved in the updated output.

## Rationale

1. **Unified access**: One function replaces the defer-only `previous_rendered` with broader availability
2. **Two sources, one interface**: The `cached` kwarg cleanly distinguishes between "what Colin produced" and "what's on disk now"
3. **Preserves manual edits**: Default behavior reads the published file, capturing any manual changes without manifest updates
4. **Graceful fallback**: Falls back to cached if published doesn't exist, handling first compile and private docs
5. **No staleness loops**: Reading own output doesn't create a self-dependency that would force constant recompilation

## Consequences

- Breaking change: `previous_rendered` removed from defer blocks
- `CompileContext` requires `config` and `output_format` parameters
- Documents can implement "edit-in-place" workflows where manual changes persist
- The mental model shifts from "Colin owns the output" to "Colin collaborates on the output"
- User edits become first-class inputs to the compilation process
