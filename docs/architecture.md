# Colin Architecture

> **Status**: MVP in development
> **Last Updated**: 2026-01-21

Colin (**Co**ntext **Lin**eage) is a context engine for the AI era. It takes interconnected source documents, resolves dependencies, applies transformations (including LLM calls), and produces outputs your agents can use.

## Core Insight: Refs as Replay Instructions

Like dbt's `ref()`, Colin's `ref()` function does double duty:
1. **Registers a dependency edge** in the graph
2. **Returns content** for use in the template

This enables automatic dependency tracking without explicit declarations.

But tracking dependencies isn't just about recording "document A depends on resource B". Colin also needs to know *when B changes* so it can recompile A. This is why references carry replay instructions.

A `Ref` contains everything needed to re-fetch the resource:

```python
Ref(
    provider="s3",               # Which provider
    connection="prod",           # Which instance (s3.prod)
    method="get",                # Which method to call
    args={"path": "bucket/key"}  # With what arguments
)
```

When checking staleness, Colin replays each Ref to get the current version (an ETag, content hash, or mtime) and compares it to the version stored at compile time. If they differ, the document is stale and needs recompilation.

Providers can implement efficient staleness checks. S3Provider uses HEAD requests for ETags. FileProvider uses stat() for mtimes. No need to fetch full content just to check if something changed.

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
4. **Compute output paths** - Determine output filename for each document based on `colin.output` setting (e.g., `config.md` → `config.json`)
5. **Build graph** - Create dependency edges mapping refs to source documents via output path
6. **Detect changes** - Compare source hashes to manifest
7. **Expand downstream** - Find all affected documents
8. **Topological sort** - Order compilation by dependencies
9. **Compile** - Render each template with Jinja
10. **Render output** - Apply format renderer (markdown passthrough, JSON extraction, YAML extraction)
11. **Process file outputs** - Extract `{% file %}` block outputs and apply their format renderers
12. **Write to cache** - Save compiled outputs to `.colin/compiled/` (main output + file outputs)
13. **Update manifest** - Record output_path, hashes, refs, LLM calls, file_outputs
14. **Publish** - Copy non-private outputs from `.colin/compiled/` to `output/` (respects per-file publish settings)

### ref() Call Flow

The `ref()` function works uniformly on all Resource types. **Project refs require the target to be compiled first** (via dependency ordering or `depends_on` hints):

```
ref("greeting.md")                              # Project ref - target must be compiled first
ref("config.json")                              # Project ref to JSON output
    │
    ├─ Looks up in compiled_outputs (in-memory, keyed by output_path)
    ├─ If not found: raises RefNotCompiledError
    ├─ Tracks Ref + version for staleness
    └─ Returns ProjectResource:
       - .content: compiled output
       - .ref(): Ref for re-fetching
       - .version: output_hash from manifest
       - .path, .relative_path: output/ paths (errors on private files)
       - .name, .description: from frontmatter
       - __str__() → .content

ref("data.md", allow_stale=True)                # Accept stale data
    │
    ├─ If in compiled_outputs: returns as normal
    ├─ If not: reads from .colin/compiled/ (previous run's output)
    └─ Returns None if never compiled

ref(colin.s3.prod.get("config.json"))           # Provider resource (no ordering needed)
    │
    ├─ Awaits the provider coroutine
    ├─ Tracks resource.ref() + resource.version
    └─ Returns the S3Resource unchanged
```

**Output path resolution**: Refs are matched to source documents via the manifest's output_path index. When you `ref("config.json")`, Colin finds the document whose `output_path == "config.json"` (source might be `config.md` with `colin.output.format: json`).

Provider functions like `s3.get()` return Resource objects. Wrapping in `ref()` registers the dependency for staleness tracking. Without `ref()`, the resource is fetched but changes won't trigger recompilation.

### Compilation Model

Colin uses a **strict static compilation model** with two distinct data sources:

- **Ordering** (what order to compile): Static AST refs + `depends_on` hints from frontmatter
- **Staleness** (what needs rebuilding): Empirical refs from manifest (what was actually used last run)

This separation ensures consistent compilation order regardless of manifest state (same behavior on fresh clone vs incremental build).

**`depends_on` hints** are required when refs can't be statically extracted (dynamic refs, `{% file %}` outputs):

```yaml
---
colin:
  depends_on:
    - generator.md
    - data-source.md
---
{% set target = 'generator.md' %}
{{ ref(target).content }}
```

**Cycles are illegal**. Use `allow_stale=True` on one side to break a cycle:

```
Cycle detected: A → B → C → A
Use allow_stale=True on one ref to break the cycle.
```

See [ADR 020: Strict Compilation Model](decisions/020-strict-compilation-model.md) for details.

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

## Storage Architecture

Colin uses a two-layer storage architecture separating build cache from published outputs:

```
project/
├── colin.toml
├── models/              # source files
├── .colin/              # build cache (fixed location)
│   ├── manifest.json    # build metadata
│   └── compiled/        # all compiled artifacts
└── output/              # published outputs only
```

**`.colin/`**: Fixed location containing all compiled artifacts and the manifest. This is the source of truth for compiled content. Should be committed to git for LLM reproducibility.

**`output/`**: Configurable output directory containing only published files. Fully managed by Colin—may be completely wiped on each compile.

### Private Files

Files can be marked as private (compiled but not published to output):

- **Naming convention**: Any path segment starting with `_` marks the file as private (`_helpers.md`, `_partials/intro.md`)
- **Frontmatter override**: `colin.output.publish: true/false` overrides the naming convention

Private files are accessible via `ref().content` but `ref().path` raises an error (linking to files that won't exist in output is a bug).

See [ADR 018: Storage Architecture](decisions/018-storage-architecture.md) and [ADR 021: Output Configuration](decisions/021-output-config.md) for details.

## Key Design Decisions

See `docs/decisions/` for detailed ADRs:

- **001-mvp-scope**: What's in/out of MVP
- **002-frontmatter-namespacing**: Why `colin:` block in frontmatter
- **003-async-first**: Why async throughout
- **004-two-pass-discovery**: Why AST parsing for refs
- **005-ref-returns-object**: Why Resource objects, not strings
- **006-plugin-architecture**: Why plugins from day one
- **007-implicit-previous**: Why no explicit `{{ previous }}` variable
- **012-provider-architecture**: Providers and storage separation
- **013-provider-template-functions**: Provider namespace + template functions
- **017-resource-and-ref-architecture**: Refs as replay instructions, Resource/Ref split
- **018-storage-architecture**: Two-layer storage, private files, cache vs published
- **020-strict-compilation-model**: Static ordering with depends_on hints, allow_stale escape hatch
- **021-output-config**: Output configuration (format, path, publish)

## Frontmatter Structure

Colin config is namespaced under `colin:` to avoid collision with document metadata:

```yaml
---
colin:
  output:
    format: markdown          # Output format (markdown, json, yaml)
    path: reports/summary.md  # Custom output path (optional)
    publish: true             # Publish to output/ (optional, default based on _ prefix)
  cache:
    policy: auto              # Cache policy (auto, always, never)
name: my-doc                  # Document metadata
description: ...              # Passed through to output
---
```

## Template Extensions

Colin templates support several Jinja block extensions:

### {% llm %} Blocks

LLM processing blocks for AI-powered transformations:

```jinja
{% llm model="sonnet" %}
Summarize this content: {{ ref("report.md") }}
{% endllm %}
```

### {% item %} Blocks

Array item markers for JSON/YAML output:

```jinja
{% for user in users %}
{% item %}
## name
{{ user.name }}

## email
{{ user.email }}
{% enditem %}
{% endfor %}
```

### {% section %} Blocks

Named sections for cross-document references:

```jinja
{% section strategy %}
## Our Strategy
Focus on growth through innovation.
{% endsection %}

{% section "key metrics" %}
## Revenue
$1M
{% endsection %}
```

Access sections from other documents:

```jinja
{{ ref("plan.md").sections.strategy }}
{{ ref("plan.md").sections['key metrics'] }}
```

**Format-aware access**: Sections return raw strings for markdown output, parsed data structures for JSON/YAML output. Sections are captured via HTML markers during rendering, stored in the manifest, and accessed via the `SectionsAccessor` class.

### {% file %} Blocks

Create additional output files from a single source document:

```jinja
{% file "path/to/output.json" format="json" %}
## name
{{ user.name }}

## role
{{ user.role }}
{% endfile %}
```

Arguments match `OutputConfig`:
- **path** (required): Relative output path for the file
- **format** (optional): Output format (`json`, `yaml`, `markdown`). Default: `markdown`
- **publish** (optional): Whether to publish to `output/`. Default: inherit from source document

**Use cases**:

1. **Generate multiple files from data**: Loop over items and create separate files
   ```jinja
   {% for tool in colin.mcp.server.tools() %}
   {% file "skills/" ~ tool.name ~ ".md" %}
   # {{ tool.name }}
   {{ tool.description }}
   {% endfile %}
   {% endfor %}
   ```

2. **Private generators producing public outputs**: A private source can create public file outputs
   ```jinja
   {# _generator.md - private source #}
   {% file "public/config.json" format="json" publish=true %}
   ## setting
   value
   {% endfile %}
   ```

3. **Auxiliary outputs**: Create supporting files alongside main output
   ```jinja
   {# report.md - main document #}
   # Report
   Main content...

   {% file "report-data.json" format="json" %}
   ## raw_data
   {{ data | tojson }}
   {% endfile %}
   ```

**Section scoping**: Sections defined inside `{% file %}` blocks are scoped to that file only. They don't leak into the parent document's sections:

```jinja
{% section main %}Main document section{% endsection %}

{% file "output.md" %}
{% section file_section %}This belongs to output.md{% endsection %}
{% endfile %}
```

Access file sections via `ref("output.md").sections.file_section`.

**Dependency ordering**: File outputs can't be statically detected. If another document refs a file output, use `depends_on` to ensure correct compilation order:

```yaml
---
colin:
  depends_on:
    - generator.md  # Produces the file I need to ref
---
{{ ref("generated-file.json").content }}
```

See [ADR 011: Multi-File Output](decisions/011-multi-file-output.md) for design details.

### {% defer %} Blocks

Deferred rendering blocks that execute in a second pass with access to the rendered document:

```jinja
# Content
Main body...

{% defer %}
## Table of Contents
{% for name in rendered.sections.keys() %}
- {{ name }}
{% endfor %}
{% enddefer %}
```

The `rendered` variable provides access to the first-pass output:
- `rendered.content`: Full document content from first pass
- `rendered.sections`: Format-aware section accessor

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
- Parallelization of LLM calls
