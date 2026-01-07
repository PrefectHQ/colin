# Colin: A Context Compiler

**Version:** 0.1 Draft
**License:** Apache 2.0
**CLI:** `colin`

---

## Executive Summary

Colin is a context compiler for the AI era. It does for agent context what dbt did for SQL: takes interconnected source documents, resolves dependencies, applies transformations (including LLM calls), and compiles to output formats like Agent Skills, system prompts, and RAG chunks.

The core insight: **dbt's `ref()` function does double duty—it registers a graph edge during parsing and returns content during rendering.** Colin applies this same pattern to context documents, where the "content" is synthesized by LLMs rather than queried from tables.

```bash
pip install colin
colin compile
```

---

## Motivation

### The Problem

Context is scattered everywhere:
- Project trackers (Linear, Jira)
- Customer conversations (calls, support tickets)
- Team documentation (Notion, Google Docs)
- Databases and data warehouses
- Internal tools and APIs

Agents need this context synthesized into useful formats:
- **Skills** they can load on-demand
- **System prompts** that shape their behavior
- **RAG chunks** they can search
- **Documentation** for humans and machines

Today, this synthesis is manual. Someone writes a skill by hand, copy-pasting from various sources, hoping they didn't miss anything. When sources change, the skill goes stale. There's no lineage, no caching, no way to know what depends on what.

### The dbt Precedent

dbt solved an analogous problem for analytics. Before dbt:
- SQL queries copy-pasted table names
- No clear dependency graph
- Changes propagated manually
- Testing was ad-hoc

dbt introduced:
- `ref('model')` — declares dependency AND returns table name
- Automatic dependency graph from refs
- Incremental compilation based on what changed
- `manifest.json` — complete lineage metadata

The SQL itself remained SQL. dbt just added a thin layer of Jinja templating with special functions.

### The Colin Opportunity

Context compilation has the same structure:
- Documents reference other documents
- Changes should propagate automatically
- LLM calls are expensive and should be cached
- Lineage matters for debugging and cost attribution

Colin applies dbt's architecture to this domain:
- `ref('doc')` — declares dependency AND returns content
- Automatic dependency graph from refs
- Incremental compilation with LLM call caching
- `manifest.json` — complete lineage and cost metadata

The documents remain Markdown. Colin just adds Jinja templating with special functions.

---

## Core Concepts

### Everything is a URI

Colin treats all content sources uniformly:

```jinja
{{ ref('context/projects/alpha') }}              {# Local Colin doc #}
{{ ref('colin://platform-team/context/infra') }} {# Remote Colin instance #}
{{ ref(mcp('linear', 'projects/alpha')) }}       {# MCP resource #}
```

The `ref()` function:
1. Fetches the content
2. Records the dependency in the manifest
3. Returns the content for use in the template

### Dependency Graph

Refs form the dependency graph. When a ref target changes, Colin knows to recompile dependent documents.

```
sources/linear-projects.colin
        │
        ▼
context/eng-health.colin ──────► skills/project-status.colin
        │
        ▼
context/team-capacity.colin
```

The graph is discovered at compile time by tracking which refs actually execute (not just which refs appear in the source).

### LLM Transformations

Most context compilation involves LLM synthesis. Colin provides filters for common operations:

```jinja
{{ ref('sources/calls') | extract('feature requests') }}
{{ ref('context/report') | summarize() }}
{{ ref('context/docs') | translate('spanish') }}
```

For complex transformations, use LLM blocks:

```jinja
{% llm model="sonnet" %}
Compare these two documents and identify contradictions:

Document A: {{ ref('context/v1') }}
Document B: {{ ref('context/v2') }}
{% endllm %}
```

LLM blocks nest—inner blocks execute first, outer blocks see their output:

```jinja
{% llm model="sonnet" %}
Synthesize these summaries into a coherent narrative:

{{ ref('source/a') | summarize() }}
{{ ref('source/b') | summarize() }}
{{ ref('source/c') | summarize() }}
{% endllm %}
```

### Caching and Stability

LLM calls are cached by a call ID:
- **Auto ID:** `hash(input_uri + filter + prompt)` — regenerates if prompt changes
- **Manual ID:** User-provided — survives prompt iteration

```jinja
{# Auto ID - regenerates if prompt changes #}
{{ ref('sources/calls') | extract('feature requests') }}

{# Manual ID - survives prompt changes, LLM sees previous output #}
{{ ref('sources/calls') | extract('feature requests', id='call-features') }}
```

When a manual ID is provided, the LLM receives its previous output and can choose to return it unchanged if the input is substantially similar.

### Output Formats

Skills are just one output format. Colin compiles to whatever you need:

```jinja
---
output: skill
name: project-health
description: Assesses engineering project health
---
```

```jinja
---
output: prompt
---
```

```jinja
---
output: rag
chunk_size: 512
---
```

```jinja
---
output: json
schema: ./schemas/status.json
---
```

---

## Syntax Reference

### File Structure

```jinja
{# context/eng-health.colin #}
---
output: skill
name: engineering-health
description: Provides engineering team health assessment
---

# Engineering Health

## Overview

This skill assesses engineering health across delivery and capacity.

## Current Status

{% for project in ref('sources/projects') | from_json %}
### {{ project.name }}
{{ project | extract('current status in 2 sentences') }}
{% endfor %}

## Recommendations

{% llm id="recommendations" model="sonnet" %}
Based on the project statuses above, provide 3 actionable recommendations.

Previous recommendations for reference:
{{ previous }}
{% endllm %}
```

### Core Functions

#### `ref(uri)` — Dependency Reference

Fetches content and registers a dependency edge.

```jinja
{{ ref('context/projects') }}                    {# Local Colin doc #}
{{ ref('colin://other-team/context/foo') }}      {# Remote Colin #}
{{ ref(mcp('linear', 'projects')) }}             {# MCP resource #}
```

#### `mcp(server, resource, **params)` — MCP Resource

Fetches from an MCP server. Wrap in `ref()` for dependency tracking.

```jinja
{# With dependency tracking #}
{{ ref(mcp('linear', 'projects', team='engineering')) }}

{# Without tracking (ephemeral) #}
{{ mcp('linear', 'projects') }}
```

#### `mcp_tool(server, tool, **params)` — MCP Tool Call

Calls an MCP tool. Side effect, not a dependency.

```jinja
{{ mcp_tool('slack', 'post_message', channel='#eng', text='...') }}
```

#### `watch(uri)` — Silent Dependency

Registers a dependency without using the content.

```jinja
{% do watch('context/trigger-rebuild') %}
```

### LLM Filters

#### `| extract(prompt, id=None)`

Extracts specific information via LLM.

```jinja
{{ ref('sources/calls') | extract('top 3 feature requests') }}
{{ ref('sources/calls') | extract('complaints', id='complaints') }}
```

#### `| summarize(id=None)`

Summarizes content via LLM.

```jinja
{{ ref('context/long-report') | summarize() }}
```

#### `| translate(language, id=None)`

Translates content via LLM.

```jinja
{{ ref('context/docs') | translate('spanish') }}
```

### LLM Blocks

For complex transformations:

```jinja
{% llm model="sonnet" %}
Your prompt here.
{{ ref('some/content') }}
{% endllm %}
```

With ID for previous output access:

```jinja
{% llm id="analysis" model="sonnet" %}
Update this analysis based on new data.

Previous version:
{{ previous }}

New data:
{{ ref('sources/data') }}
{% endllm %}
```

### Pin Blocks

Frozen content inside LLM blocks that the LLM must preserve:

```jinja
{% llm model="sonnet" %}
Write a report that includes this exact section:

{% pin %}
## Methodology
This analysis uses the standard DORA metrics framework.
{% endpin %}

Data: {{ ref('sources/metrics') }}
{% endllm %}
```

Pin options:
- `{% pin %}` — LLM writes around it (default)
- `{% pin position="start" %}` — LLM only writes after
- `{% pin position="end" %}` — LLM only writes before

### File Generation

Generate multiple output files from one source:

```jinja
---
output: skill
name: project-status
---

# Project Status

Main content here.

{% file 'REFERENCE.md' %}
## API Reference
{{ ref('context/api-docs') }}
{% endfile %}

{% for project in ref('sources/projects') | from_json %}
{% file 'projects/{{ project.slug }}.md' %}
## {{ project.name }}
{{ project | extract('detailed summary') }}
{% endfile %}
{% endfor %}
```

### Diff Filters

Compare current state to previous compile:

```jinja
{{ ref('kb://node-123').edges | new() }}       {# Added since last compile #}
{{ ref('kb://node-123').edges | changed() }}   {# Modified since last compile #}
{{ ref('sources/projects') | diff().added }}   {# Structured diff #}
```

### Special Variables

#### `compiled.previous`

The entire previously compiled document:

```jinja
{% llm model="sonnet" %}
Update this document, maintaining its structure:

{{ compiled.previous }}

New information:
{{ ref('sources/updates') }}
{% endllm %}
```

#### `previous`

Inside an LLM block with an ID, the previous output of that block:

```jinja
{% llm id="summary" model="sonnet" %}
Previous: {{ previous }}
New data: {{ ref('sources/data') }}
{% endllm %}
```

---

## Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                           Colin CLI                                │
│  compile, serve, graph, watch, clean                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Colin Core                                │
│                                                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │   Parser    │  │   Graph     │  │   Compiler              │ │
│  │             │  │             │  │                         │ │
│  │ - Jinja AST │  │ - URI→URI   │  │ - Jinja env            │ │
│  │ - Ref       │  │ - Topo sort │  │ - LLM calls            │ │
│  │   extract   │  │ - Cycle     │  │ - Caching              │ │
│  │             │  │   detect    │  │                         │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    Manifest Storage                         ││
│  │  - Document metadata (hashes, refs, costs)                  ││
│  │  - LLM call cache                                           ││
│  │  - Resource cache                                           ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  Input Plugins  │  │Transform Plugins│  │ Output Plugins  │
│                 │  │                 │  │                 │
│  - file://      │  │  - extract()    │  │  - skill        │
│  - colin://     │  │  - summarize()  │  │  - prompt       │
│  - mcp://       │  │  - translate()  │  │  - rag          │
│  - postgres://  │  │  - custom       │  │  - json         │
└─────────────────┘  └─────────────────┘  └─────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Materialization Plugins                         │
│                                                                 │
│  dag       - Topo sort, fails on cycles, in-memory              │
│  bfs       - Handles cycles, visits each node once              │
│  streaming - Dynamic discovery, external state, unbounded       │
└─────────────────────────────────────────────────────────────────┘
```

### Plugin Interfaces

#### Input Plugin

```python
class InputPlugin(Protocol):
    scheme: str  # "mcp", "file", "postgres", etc.
    
    def fetch(self, uri: str) -> Resource:
        """Get content + metadata"""
        ...
    
    def hash(self, uri: str) -> str:
        """Content hash for change detection"""
        ...
    
    def subscribe(self, uri: str, callback: Callable) -> Unsubscribe:
        """Optional: push notifications on change"""
        ...
```

#### Output Plugin

```python
class OutputPlugin(Protocol):
    name: str  # "skill", "prompt", "rag"
    
    def emit(self, doc: CompiledDoc) -> dict[Path, str]:
        """
        Given compiled doc, return files to write.
        E.g., skill returns SKILL.md + supporting files.
        """
        ...
```

#### Transform Plugin

```python
class TransformPlugin(Protocol):
    name: str  # "extract", "summarize"
    
    def transform(
        self, 
        content: str, 
        previous: str | None,
        **kwargs
    ) -> str:
        """Apply transformation, optionally considering previous output"""
        ...
    
    def cache_key(self, content: str, **kwargs) -> str:
        """Hash for caching"""
        ...
```

#### Materialization Plugin

```python
class MaterializationPlugin(Protocol):
    name: str  # "dag", "bfs", "streaming"
    
    def materialize(
        self,
        changed: set[str],
        graph: Graph,
        compile: Callable[[str], CompiledDoc],
        persist: Callable[[str, CompiledDoc], None],
    ) -> None:
        """
        Compile affected documents in appropriate order.
        """
        ...
```

### Manifest Structure

```json
{
  "version": "1",
  "compiled_at": "2024-01-15T10:00:00Z",
  
  "documents": {
    "context/eng-health": {
      "source_hash": "abc123",
      "output_hash": "def456",
      "compiled_at": "2024-01-15T10:00:00Z",
      "refs_evaluated": [
        "context/projects/alpha",
        "mcp://linear/projects"
      ],
      "llm_calls": {
        "auto:abc123": {
          "input_hash": "ghi789",
          "output_hash": "jkl012",
          "output": "...",
          "cost_usd": 0.002,
          "model": "haiku"
        },
        "manual:recommendations": {
          "input_hash": "mno345",
          "output_hash": "pqr678",
          "output": "...",
          "cost_usd": 0.01,
          "model": "sonnet"
        }
      },
      "total_cost_usd": 0.012
    }
  },
  
  "resources": {
    "mcp://linear/projects": {
      "content_hash": "xyz789",
      "fetched_at": "2024-01-15T09:55:00Z"
    }
  }
}
```

### Storage Options

```yaml
# colin.yaml

# For skills (small graphs, git-friendly)
storage: json

# For KB (large graphs, concurrent access)
storage: sqlite

# For distributed systems
storage: postgres
```

All storage backends implement the same interface:

```python
class ManifestStorage(Protocol):
    def get_document(self, uri: str) -> DocMeta | None: ...
    def set_document(self, uri: str, meta: DocMeta): ...
    def get_dependents(self, uri: str) -> list[str]: ...
    def get_all_documents(self) -> dict[str, DocMeta]: ...
    def atomic_update(self, updates: dict[str, DocMeta]): ...
```

### Cache Structure

```
.colin/
  manifest.json           # Or manifest.db for SQLite
  cache/
    llm/
      jkl012.txt          # LLM outputs by hash
      pqr678.txt
    resources/
      xyz789.json         # Fetched MCP content by hash
```

Content-addressed storage. Manifest has hashes pointing to cache files.

---

## Execution Model

### Compile Flow

```python
def compile_all():
    # 1. Discover all .colin files
    all_docs = find_colin_files()
    
    # 2. Load manifest
    manifest = load_manifest()
    
    # 3. Find what needs recompiling
    changed = set()
    for uri in all_docs:
        if needs_recompile(uri, manifest):
            changed.add(uri)
    
    # 4. Get stored refs to find dependents
    graph = build_graph_from_manifest(manifest)
    
    # 5. Expand to all affected documents
    affected = downstream_closure(changed, graph)
    
    # 6. Materialize (plugin determines order)
    materialization_plugin.materialize(
        changed=affected,
        graph=graph,
        compile=compile_document,
        persist=update_manifest
    )
    
    # 7. Save manifest
    save_manifest()
```

### Change Detection

```python
def needs_recompile(uri: str, manifest: Manifest) -> bool:
    doc = manifest.get_document(uri)
    
    if not doc:
        return True  # New document
    
    # Source file changed?
    if hash_file(uri) != doc.source_hash:
        return True
    
    # Any evaluated ref changed?
    for ref_uri in doc.refs_evaluated:
        if ref_changed(ref_uri, manifest):
            return True
    
    return False

def ref_changed(uri: str, manifest: Manifest) -> bool:
    if uri.startswith('colin://'):
        # Remote Colin - fetch and check hash
        resource = fetch_remote_colin(uri)
        cached = manifest.get_resource(uri)
        return resource.hash != cached.content_hash
    
    elif uri.startswith('mcp://'):
        # MCP resource - fetch and hash content
        content = fetch_mcp_resource(uri)
        current_hash = hash(content)
        cached = manifest.get_resource(uri)
        return current_hash != cached.content_hash
    
    else:
        # Local Colin doc - check output hash
        ref_doc = manifest.get_document(uri)
        return ref_doc is None or ref_doc.output_hash != cached_output_hash
```

### Document Compilation

```python
def compile_document(uri: str) -> CompiledDoc:
    template = parse_jinja(uri)
    ctx = CompileContext(manifest)
    
    # Build Jinja environment with our functions
    env = jinja2.Environment()
    env.globals['ref'] = ctx.ref
    env.globals['mcp'] = ctx.mcp
    env.globals['watch'] = ctx.watch
    env.filters['extract'] = ctx.extract_filter
    env.filters['summarize'] = ctx.summarize_filter
    # etc.
    
    # Render template
    output = template.render(env)
    
    return CompiledDoc(
        uri=uri,
        source_hash=hash_file(uri),
        output=output,
        output_hash=hash(output),
        refs_evaluated=ctx.refs_evaluated,
        llm_calls=ctx.llm_calls,
        total_cost=ctx.total_cost
    )
```

### LLM Call Handling

```python
class CompileContext:
    def __init__(self, manifest: Manifest):
        self.manifest = manifest
        self.refs_evaluated = []
        self.llm_calls = {}
        self.total_cost = 0
    
    def extract_filter(
        self, 
        content: str, 
        prompt: str, 
        id: str | None = None
    ) -> str:
        # Determine call ID
        call_id = id or f"auto:{hash(content + 'extract' + prompt)}"
        
        # Check for cache hit (exact input match)
        prev_call = self.manifest.get_llm_call(call_id)
        if prev_call and prev_call.input_hash == hash(content):
            return prev_call.output
        
        # Build system prompt
        system = """
        Extract the requested information from the provided content.
        If previous output is provided and still accurate, return it unchanged.
        """
        
        user = f"""
        <content>
        {content}
        </content>
        
        <previous_output>
        {prev_call.output if prev_call else "None"}
        </previous_output>
        
        <instruction>
        Extract: {prompt}
        </instruction>
        """
        
        # Call LLM
        result = call_llm(model="haiku", system=system, user=user)
        
        # Record call
        self.llm_calls[call_id] = LLMCall(
            input_hash=hash(content),
            output_hash=hash(result.text),
            output=result.text,
            cost_usd=result.cost,
            model="haiku"
        )
        self.total_cost += result.cost
        
        return result.text
```

### Parallelization

LLM calls within a document are independent by default and can run in parallel:

```python
def compile_document_parallel(uri: str) -> CompiledDoc:
    template = parse_jinja(uri)
    
    # Phase 1: Identify all LLM calls from AST
    calls = extract_llm_calls(template)
    
    # Phase 2: Build dependency graph (nested blocks depend on children)
    call_graph = build_call_graph(calls)
    
    # Phase 3: Execute in parallel batches
    results = {}
    for batch in topological_batches(call_graph):
        # All calls in a batch run concurrently
        futures = {
            call.id: executor.submit(execute_call, call)
            for call in batch
        }
        for call_id, future in futures.items():
            results[call_id] = future.result()
    
    # Phase 4: Render with resolved values
    output = render_with_results(template, results)
    
    return CompiledDoc(...)
```

Each call gets:
- Its input content
- Its previous output (by call ID)

NOT "the document compiled so far" — that would enforce sequential execution.

If you need coherence between sections, wrap them in an outer LLM block that synthesizes.

---

## Colin as MCP Server

Colin can serve compiled documents as MCP resources:

```bash
colin serve --port 8080
```

### Resources Exposed

```typescript
// List resources
GET /resources
→ [
    { uri: "colin://self/context/eng-health", name: "Engineering Health", ... },
    { uri: "colin://self/skills/project-status", name: "Project Status Skill", ... }
  ]

// Get resource
GET /resources/colin://self/context/eng-health
→ {
    uri: "colin://self/context/eng-health",
    content: "# Engineering Health\n\n...",
    metadata: {
      content_hash: "abc123",
      compiled_at: "2024-01-15T10:00:00Z",
      refs: ["colin://self/sources/linear", ...],
      cost_usd: 0.05
    }
  }
```

### Subscriptions

Other systems can subscribe to changes:

```typescript
SUBSCRIBE colin://self/context/eng-health

// When document recompiles:
→ { type: "resource_updated", uri: "...", new_hash: "def456" }
```

### Cross-Instance References

Team A's Colin instance can reference Team B's:

```jinja
{# In Team A's context/company-health.colin #}
{{ ref('colin://team-b.internal:8080/context/their-metrics') }}
```

Full lineage preserved across organizational boundaries.

### Tools Exposed

```typescript
// Trigger recompile
POST /tools/compile
{ path: "context/eng-health" }

// Get dependency graph
POST /tools/graph
{ root: "skills/project-status" }

// Search across all context
POST /tools/search
{ query: "customer feature requests" }
```

---

## CLI Reference

### `colin compile`

Compile all documents (or specific paths):

```bash
colin compile                      # Compile everything that needs it
colin compile context/eng-health   # Compile specific doc (and deps)
colin compile --no-cache           # Ignore cache, recompile all
colin compile --parallel 4         # Limit parallelism
```

### `colin serve`

Run as MCP server:

```bash
colin serve                        # Default port 8080
colin serve --port 9000            # Custom port
colin serve --watch                # Recompile on file changes
```

### `colin graph`

Visualize dependencies:

```bash
colin graph                        # Full graph
colin graph context/eng-health     # From specific node
colin graph --changed              # Only nodes that would recompile
colin graph --format dot           # Output as Graphviz DOT
colin graph --format json          # Output as JSON
```

### `colin watch`

Watch for changes and recompile:

```bash
colin watch                        # Watch all sources
colin watch --serve                # Also run MCP server
```

### `colin clean`

Clear caches:

```bash
colin clean                        # Clear LLM cache
colin clean --all                  # Clear everything including manifest
```

### `colin cost`

Show LLM costs:

```bash
colin cost                         # Total cost
colin cost context/eng-health      # Cost for specific doc
colin cost --since 2024-01-01      # Cost since date
colin cost --by-model              # Breakdown by model
```

---

## Configuration

### colin.yaml

```yaml
# Source directories
sources:
  - context/
  - sources/
  - skills/

# Output directory
output:
  dir: dist/

# Storage backend
storage: json  # or: sqlite, postgres

# Default LLM settings
llm:
  default_model: haiku
  cache: true
  
# MCP servers
mcp:
  servers:
    linear:
      command: npx @linear/mcp-server
    postgres:
      command: npx @anthropic/postgres-mcp
      env:
        DATABASE_URL: ${DATABASE_URL}

# Plugins
plugins:
  inputs:
    - colin.plugins.file
    - colin.plugins.mcp
  outputs:
    - colin.plugins.skill
    - colin.plugins.rag
  transforms:
    - colin.plugins.llm
  materialization: dag  # or: bfs, streaming

# Remote Colin instances
remotes:
  platform: https://platform-colin.internal:8080
  product: https://product-colin.internal:8080
```

---

## User Stories

### Story 1: Creating a Project Status Skill

**As a** engineering manager
**I want to** create a skill that summarizes project status from Linear
**So that** my team's agents can answer project questions accurately

```jinja
{# sources/linear-projects.colin #}
---
refresh: 1h
---
{{ mcp('linear', 'projects', team='engineering') | json }}
```

```jinja
{# skills/project-status.colin #}
---
output: skill
name: project-status
description: Provides current project status and risk assessment
---

# Project Status

## Current Projects

{% for p in ref('sources/linear-projects') | from_json %}
### {{ p.name }}

{{ p | extract('status, timeline, and top risk in 3 sentences', id=p.id) }}

{% endfor %}

## Overall Assessment

{% llm id="assessment" model="sonnet" %}
Based on the projects above, provide:
1. Overall health assessment
2. Top 3 risks across all projects
3. Recommended actions

Previous assessment for continuity:
{{ previous }}
{% endllm %}
```

```bash
colin compile
# Output: dist/project-status/SKILL.md
```

### Story 2: Incremental Knowledge Base Updates

**As a** knowledge engineer
**I want to** update concept documents when new edges are added
**So that** the KB stays current without full regeneration

```jinja
{# kb/concepts/customer-churn.colin #}
---
output: json
storage: sqlite
materialization: bfs
---

{% set node = ref('kb://concepts/customer-churn') %}
{% set new_edges = node.edges | new() %}

{% if new_edges %}
{% llm id="concept" model="sonnet" %}
Update this concept document with new information.

Current document:
{{ previous }}

New connections:
{% for edge in new_edges %}
- {{ edge.type }}: {{ edge.target.summary }}
{% endfor %}

Integrate relevant new information. Preserve structure.
{% endllm %}
{% else %}
{{ previous }}
{% endif %}
```

### Story 3: Multi-Team Context Aggregation

**As an** executive
**I want to** see a unified view across engineering and product
**So that** I can make informed decisions

```jinja
{# context/exec-summary.colin #}
---
output: prompt
---

You have access to the following context about the company:

## Engineering Status
{{ ref('colin://eng-team/context/health') | summarize() }}

## Product Roadmap
{{ ref('colin://product-team/context/roadmap') | summarize() }}

## Customer Sentiment
{{ ref('context/customer-sentiment') | summarize() }}

Use this context to answer questions about company status.
```

### Story 4: Dynamic Documentation Generation

**As a** developer
**I want to** generate API docs from OpenAPI spec
**So that** docs stay in sync with the API

```jinja
{# context/api-docs.colin #}
---
output: skill
name: api-reference
description: API documentation and usage examples
---

# API Reference

{% for endpoint in ref(mcp('openapi', 'endpoints')) %}
## {{ endpoint.method }} {{ endpoint.path }}

{{ endpoint.description }}

{% file 'examples/{{ endpoint.operationId }}.md' %}
### Example

{% llm model="haiku" %}
Generate a practical curl example for this endpoint:
{{ endpoint | json }}
{% endllm %}
{% endfile %}

{% endfor %}
```

---

## Implementation Roadmap

### Phase 1: Core (MVP)

**Goal:** Compile skills from Jinja templates with LLM transforms

- [ ] Jinja environment with `ref()`, `| extract()`, `| summarize()`
- [ ] `{% llm %}` blocks
- [ ] JSON manifest storage
- [ ] File-based input plugin
- [ ] Skill output plugin
- [ ] Basic CLI: `colin compile`
- [ ] LLM call caching (by content hash)

**Deliverable:** Can compile a skill from .colin files

### Phase 2: Dependencies

**Goal:** Incremental compilation based on changes

- [ ] Change detection (source hash, ref hash)
- [ ] Dependency graph from evaluated refs
- [ ] `watch()` function
- [ ] Downstream propagation
- [ ] `colin graph` command
- [ ] `colin watch` command

**Deliverable:** Only recompiles what changed

### Phase 3: MCP Integration

**Goal:** Fetch from and serve as MCP

- [ ] MCP input plugin
- [ ] MCP resource fetching and hashing
- [ ] `colin serve` command
- [ ] Resource subscriptions
- [ ] Remote Colin references (`colin://`)

**Deliverable:** Full MCP citizen

### Phase 4: Advanced Features

**Goal:** Production-ready features

- [ ] Manual call IDs with `previous` access
- [ ] `{% pin %}` blocks
- [ ] `{% file %}` directive
- [ ] `| new()`, `| changed()`, `| diff()` filters
- [ ] Parallelization of LLM calls
- [ ] Prefect integration for observability
- [ ] Cost tracking and reporting
- [ ] SQLite manifest storage

**Deliverable:** Feature-complete for skills use case

### Phase 5: Knowledge Base

**Goal:** Support cyclic graphs and large scale

- [ ] BFS materialization strategy
- [ ] Streaming/dynamic materialization
- [ ] Postgres manifest storage
- [ ] Incremental edge processing
- [ ] `compiled.previous` document access

**Deliverable:** Can power knowledge base updates

### Phase 6: Ecosystem

**Goal:** Extensibility and integrations

- [ ] Plugin discovery (entry points)
- [ ] Additional output plugins (RAG, prompt, JSON)
- [ ] Additional input plugins (Postgres, Snowflake)
- [ ] Additional transform plugins (custom LLM operations)
- [ ] Registry for cross-org discovery

**Deliverable:** Extensible platform

---

## Open Questions

1. **Pin syntax inside LLM blocks** — How do we instruct the LLM to write around pinned content? Is this reliably achievable with prompt engineering, or do we need a post-processing step?

2. **Loop iteration identity** — When iterating over dynamic data, how do we provide stable IDs for `previous` access? Requiring `id=item.id` feels right, but need to validate UX.

3. **Cycle handling semantics** — For KB use case, what consistency guarantees do we provide? Eventual consistency with N rounds? User-controlled convergence?

4. **MCP metadata extensions** — Should Colin-aware MCP resources return metadata in a standard format? What fields? How do we handle non-Colin resources gracefully?

5. **Skill structure** — Current Anthropic skills are directories with specific conventions. Do we mirror that exactly, or provide flexibility? How do we handle scripts and resources?

6. **Cost controls** — Should there be budget limits per compile? Per document? Alerts when costs exceed thresholds?

---

## Appendix: Comparison to dbt

| Aspect                 | dbt                  | Colin                          |
| ---------------------- | -------------------- | ------------------------------ |
| Source files           | `.sql`               | `.colin` (markdown + jinja)    |
| Templating             | Jinja                | Jinja                          |
| Dependency declaration | `ref('model')`       | `ref('doc')`                   |
| Dependency returns     | Table name (for SQL) | Content (for LLM)              |
| Transformation         | SQL query            | LLM synthesis                  |
| Output                 | Tables in warehouse  | Files (skills, prompts, etc.)  |
| Manifest               | `manifest.json`      | `manifest.json` (or SQLite)    |
| Change detection       | Source hash          | Source hash + ref content hash |
| Incremental            | Yes (based on state) | Yes (based on content hash)    |
| Graph shape            | DAG (enforced)       | DAG or cyclic (configurable)   |
| Caching                | Warehouse handles it | Colin caches LLM outputs       |

---

## Appendix: Example Project Structure

```
my-context/
├── colin.yaml
├── sources/
│   ├── linear-projects.colin      # MCP wrapper
│   ├── customer-calls.colin       # MCP wrapper
│   └── team-data.colin            # Static data
├── context/
│   ├── projects/
│   │   ├── alpha.colin
│   │   └── beta.colin
│   ├── team/
│   │   └── capacity.colin
│   └── eng-health.colin           # Aggregates projects + team
├── skills/
│   ├── project-status/
│   │   ├── SKILL.colin            # Main skill
│   │   └── scripts/
│   │       └── helper.py          # Static resource
│   └── customer-insights.colin
├── prompts/
│   └── support-agent.colin        # System prompt
├── dist/                          # Compiled output
│   ├── skills/
│   │   └── project-status/
│   │       ├── SKILL.md
│   │       └── scripts/
│   │           └── helper.py
│   └── prompts/
│       └── support-agent.txt
└── .colin/
    ├── manifest.json
    └── cache/
        ├── llm/
        └── resources/
```

---

*This document represents the current state of Colin's design as of the initial planning phase. It will evolve as implementation progresses and we learn from real usage.*