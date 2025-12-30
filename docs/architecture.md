# Colin Architecture

> **Status**: MVP in development
> **Last Updated**: 2024-12-27

Colin (**Co**ntext **Lin**eage) is a context compiler for the AI era. It takes interconnected source documents, resolves dependencies, applies transformations (including LLM calls), and compiles them to output formats.

## Core Insight

Like dbt's `ref()`, Colin's `ref()` function does double duty:
1. **Registers a dependency edge** in the graph
2. **Returns content** for use in the template

This enables automatic dependency tracking without explicit declarations.

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                           Colin CLI                               │
│  compile [--no-cache] [--dry-run]                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Colin Core                               │
│                                                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │   Loader    │  │   Graph     │  │   Compiler              │ │
│  │             │  │             │  │                         │ │
│  │ - Discovery │  │ - URI→URI   │  │ - Jinja env            │ │
│  │ - Frontmatter│ │ - Topo sort │  │ - LLM blocks           │ │
│  │ - AST parse │  │ - Cycle     │  │ - Filters              │ │
│  │             │  │   detect    │  │ - Caching              │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    Manifest (JSON)                          ││
│  │  - Document metadata (hashes, refs, costs)                  ││
│  │  - LLM call cache                                           ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  Input Plugins  │  │ Output Plugins  │  │ Materialization │
│                 │  │                 │  │                 │
│  - file (MVP)   │  │  - markdown     │  │  - dag (MVP)    │
│  - mcp (future) │  │    (MVP)        │  │  - bfs (future) │
│  - colin://     │  │  - skill        │  │                 │
│    (future)     │  │    (future)     │  │                 │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

## Package Structure

```
src/colin/
├── __init__.py
├── __main__.py           # python -m colin entry point
├── cli.py                # cyclopts CLI
├── models.py             # Pydantic models
├── loader.py             # Document discovery + frontmatter
├── graph.py              # Dependency graph + topo sort
├── storage.py            # Manifest JSON read/write
├── exceptions.py         # Custom exceptions
├── compiler/
│   ├── context.py        # CompileContext (tracks refs, LLM calls)
│   ├── engine.py         # Main compile orchestration
│   └── jinja_env.py      # Async Jinja environment
├── extensions/
│   ├── llm_block.py      # {% llm %}...{% endllm %}
│   └── filters.py        # | extract() filter
├── llm/
│   ├── base.py           # LLMProvider protocol
│   └── stub.py           # StubLLMProvider (for testing)
└── plugins/
    ├── base.py           # Plugin protocols
    ├── inputs/
    │   └── file.py       # Local file input
    ├── outputs/
    │   └── markdown.py   # Raw markdown output
    └── materialization/
        └── dag.py        # Topological DAG
```

## Key Data Flows

### Compile Flow

1. **Discover** - Find all `.colin` files in source directories
2. **Load** - Parse frontmatter and template content
3. **Extract refs** - Two-pass AST parsing to find `ref()` calls
4. **Build graph** - Create dependency edges from refs
5. **Detect changes** - Compare source hashes to manifest
6. **Expand downstream** - Find all affected documents
7. **Topological sort** - Order compilation by dependencies
8. **Compile** - Render each template with Jinja
9. **Write outputs** - Save to dist/ directory
10. **Update manifest** - Record hashes, refs, LLM calls

### ref() Call Flow

```
ref('context/foo')
    │
    ├─ Records dependency edge: current_doc → context/foo
    │
    ├─ Fetches compiled content from dist/context/foo.md
    │
    └─ Returns RefResult object:
       - .name: "foo" (from frontmatter or URI)
       - .description: "..." (from frontmatter)
       - .content: "..." (compiled output)
       - .template: "..." (raw source)
       - .updated: datetime
       - .uri: "context/foo"
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

## Plugin Protocols

### InputPlugin
```python
class InputPlugin(Protocol):
    scheme: str  # "file", "mcp", "colin"
    async def fetch(self, uri: str) -> RefResult: ...
    async def hash(self, uri: str) -> str: ...
```

### OutputPlugin
```python
class OutputPlugin(Protocol):
    name: str  # "markdown", "skill"
    async def emit(self, doc: CompiledDocument, output_dir: Path) -> list[Path]: ...
```

### MaterializationPlugin
```python
class MaterializationPlugin(Protocol):
    name: str  # "dag", "bfs"
    async def materialize(
        self,
        changed: set[str],
        graph: DependencyGraph,
        compile_fn: Callable[[str], Awaitable[CompiledDocument]],
    ) -> list[str]: ...
```

## MVP Limitations

Current implementation excludes:
- MCP integration
- Remote `colin://` refs
- `{% pin %}` blocks
- Watch mode
- Skills output format
- Actual LLM calls (stub only)
- Parallelization of LLM calls
