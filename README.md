# Colin

**Co**ntext **Lin**eage — a compiler for the AI era.

Colin takes interconnected source documents, resolves dependencies, applies transformations (including LLM calls), and compiles them to output formats. It's the happiest way to build agent context.

> *Named for the perpetually cheerful robot from The Hitchhiker's Guide to the Galaxy.*

## Installation

```bash
uv add colin
```

## Quick Start

Create a `.colin` file in `context/`:

```markdown
---
colin:
  output: markdown
name: Engineering Health
description: Weekly engineering team health summary
---

# Engineering Health Report

{{ ref('sources/github-issues') | extract('open bug count') }}

{% llm %}
Summarize the engineering health based on the data above.
{% endllm %}
```

Compile your documents:

```bash
cbt compile
```

## Core Concepts

### ref() - Dependency Resolution

The `ref()` function registers a dependency and returns the compiled content of another document:

```jinja
{{ ref('context/team-roster') }}
```

It returns a structured `RefResult` with:

- `.name` - Document name from frontmatter
- `.description` - Document description
- `.content` - Compiled output (also returned by `str()`)
- `.template` - Raw source template
- `.updated` - Last compilation timestamp
- `.uri` - The ref URI

### LLM Blocks

Use `{% llm %}` blocks for LLM-powered transformations:

```jinja
{% llm %}
Given this data:
{{ ref('sources/metrics') }}

Identify the top 3 concerns.
{% endllm %}
```

With explicit model and caching ID:

```jinja
{% llm model="sonnet" id="weekly-summary" %}
Summarize the week's activity.
{% endllm %}
```

### Extract Filter

Extract specific information from content:

```jinja
{{ ref('sources/slack-export') | extract('action items') }}
{{ content | extract('key decisions', id='decisions-extract') }}
```

### Frontmatter

Colin uses YAML frontmatter with a `colin:` namespace for configuration:

```yaml
---
colin:
  output: markdown
name: My Document
description: A helpful description
custom_field: any metadata you want
---
```

## CLI Commands

```bash
cbt compile              # Compile all documents
cbt compile --force      # Force recompile everything
cbt compile --dry-run    # Show what would be compiled
cbt compile --verbose    # Detailed output with costs

cbt status               # Show compilation status
cbt clean                # Remove outputs and manifest
```

## How It Works

1. **Discovery** - Find all `.colin` files in source directories
2. **AST Parsing** - Extract `ref()` calls to build dependency graph
3. **Topological Sort** - Order documents so dependencies compile first
4. **Compilation** - Render Jinja templates with LLM transformations
5. **Caching** - Store results in manifest for incremental rebuilds

## Caching

Colin caches LLM calls to avoid redundant API calls:

- **Auto IDs** (default): Hash-based, cache hits when input is identical
- **Manual IDs**: Stable across prompt changes, receives previous output for consistency

```jinja
{# Auto ID - caches on exact input match #}
{{ content | extract('summary') }}

{# Manual ID - maintains stability across prompt tweaks #}
{{ content | extract('summary', id='main-summary') }}
```

## Project Structure

```text
your-project/
├── context/           # Source .colin files
│   ├── reports/
│   │   └── weekly.colin
│   └── summaries/
│       └── team.colin
├── target/            # Compiled output (git-ignored)
└── .colin-manifest.json  # Build cache (git-ignored)
```

## License

MIT
