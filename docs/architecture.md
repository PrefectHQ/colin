# Colin Architecture

> **Status**: MVP in development
> **Last Updated**: 2025-01-06

Colin (**Co**ntext **Lin**eage) is a context engine for the AI era. It takes interconnected source documents, resolves dependencies, applies transformations (including LLM calls), and produces outputs your agents can use.

## Core Insight

Like dbt's `ref()`, Colin's `ref()` function does double duty:
1. **Registers a dependency edge** in the graph
2. **Returns content** for use in the template

This enables automatic dependency tracking without explicit declarations.

## System Overview

```
┌──────────────────────────────────────────────────────────────┐
│                         Colin CLI                             │
│  run / compile / mcp                                           │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                        Compile Engine                         │
│  - Discovery + frontmatter                                    │
│  - Dependency graph                                           │
│  - Jinja environment + LLM blocks                             │
│  - Manifest update (refs, LLM calls)                          │
└──────────────────────────────────────────────────────────────┘
          │                      │                    │
          ▼                      ▼                    ▼
┌────────────────────┐  ┌───────────────────┐  ┌──────────────────┐
│ Providers          │  │ Storage           │  │ Manifest         │
│ - project://       │  │ - artifacts       │  │ - refs           │
│ - mcp.<name>://    │  │ - outputs         │  │ - ref_versions   │
│ - custom schemes   │  │                   │  │ - llm_calls      │
└────────────────────┘  └───────────────────┘  └──────────────────┘
```

## Package Structure

```
src/colin/
├── api/                  # project, compile, and mcp helpers
├── cli/                  # cyclopts CLI commands
├── compiler/             # engine, context, jinja env, state
├── extensions/           # Jinja extensions + filters
├── providers/            # providers + storage backends
│   ├── base.py           # Provider base class
│   ├── context.py        # ProviderContext + Reference
│   ├── manager.py        # Provider registry + lifecycle
│   ├── namespace.py      # Template namespace binding
│   ├── mcp.py            # MCP provider
│   ├── llm.py            # LLM provider functions
│   ├── project.py        # project:// provider
│   └── storage/          # Storage providers (read+write)
├── renders/              # Renderers (markdown/json/yaml)
├── llm/                  # LLM prompt helpers
├── models.py             # Pydantic models
└── plugins/              # Legacy protocols (not wired to engine)
```

## Key Data Flows

### Compile Flow

1. **Discover** - Find all `.md` models in the source directory
2. **Load** - Parse frontmatter and template content
3. **Extract refs** - Two-pass AST parsing to find `ref()` calls
4. **Build graph** - Create dependency edges from refs
5. **Detect changes** - Compare source hashes to manifest
6. **Expand downstream** - Find all affected documents
7. **Topological sort** - Order compilation by dependencies
8. **Compile** - Render each template with Jinja
9. **Write outputs** - Save compiled outputs via artifact storage
10. **Update manifest** - Record hashes, refs, LLM calls

### ref() Call Flow

```
ref('context/foo')
    │
    ├─ Normalizes to project://context/foo.md
    ├─ Records dependency edge: current_doc → project://context/foo.md
    ├─ Routes by scheme:
    │   - project:// → artifact storage
    │   - other://   → provider.read(path)
    └─ Returns RefResult object:
       - .name: "foo" (from frontmatter or URI)
       - .description: "..." (from frontmatter)
       - .content: "..." (compiled output)
       - .template: "..." (raw source)
       - .updated: datetime
       - .uri: "project://context/foo.md"
       - __str__() → .content
```

### LLM Caching Flow

```
LLM call with id (auto or manual)
    │
    ├─ Compute call_id:
    │   - Auto: hash(input + operation + params)
    │   - Manual: user-provided string
    │
    ├─ Check cache in manifest:
    │   - Same call_id + same input_hash → return cached output
    │
    └─ Cache miss:
        - Call LLM (or stub)
        - Include previous output for stability (if exists)
        - Store result in manifest
```

## Key Design Decisions

See `docs/decisions/` for detailed ADRs:

- **001-mvp-scope**: What's in/out of MVP
- **002-frontmatter-namespacing**: Why `colin:` block in frontmatter
- **003-async-first**: Why async throughout
- **004-two-pass-discovery**: Why AST parsing for refs
- **005-ref-returns-object**: Why RefResult, not string
- **006-plugin-architecture**: Why plugins from day one
- **007-implicit-previous**: Why no explicit `{{ previous }}` variable
- **012-provider-architecture**: Providers and storage separation
- **013-provider-template-functions**: Provider namespace + template functions

## Frontmatter Structure

Colin config is namespaced under `colin:` to avoid collision with document metadata:

```yaml
---
colin:
  output: markdown    # Colin config
name: my-doc          # Document metadata
description: ...      # Passed through to output
---
```

## Providers and Template Functions

Providers handle scheme-based reads (`project://`, `mcp.<name>://`, and custom schemes). Storage providers also write compiled outputs.

Providers can contribute template functions via `Provider.get_functions()`. These are bound under the `colin` namespace:

```jinja
{{ colin.mcp.github.resource("repo://owner/repo/readme") }}
{{ extract(ref("context/summary").content, "summarize") }}
```

Provider functions return `Resource` objects (content + ref + version). Resources are tracked via `ref_versions` for version-based staleness detection.

## MVP Limitations

Current implementation excludes:
- Remote `colin://` refs
- `{% pin %}` blocks
- Watch mode
- Skills output format
- Actual LLM calls (stub only)
- Parallelization of LLM calls
