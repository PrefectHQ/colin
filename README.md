# Colin

**Co**ntext **Lin**eage — a compiler for the AI era.

Colin takes interconnected source documents, resolves dependencies, applies transformations (including LLM calls), and compiles them to output formats.

> *Named for the perpetually cheerful robot from The Hitchhiker's Guide to the Galaxy.*

## Installation

```bash
uv add colin
```

## Quick Start

```bash
cbt init                 # Create colin.toml and models/
```

Create a markdown file in `models/`:

```markdown
---
name: Engineering Health
description: Weekly engineering team health summary
---

# Engineering Health Report

{{ ref('sources/github-issues') | extract('open bug count') }}

{% llm %}
Summarize the engineering health based on the data above.
{% endllm %}
```

Compile:

```bash
cbt run                  # Compile all documents
```

## Features

### ref() — Dependency Resolution

Reference other documents. Colin builds a dependency graph and compiles in order:

```jinja
{{ ref('context/team-roster') }}
```

Returns a `RefResult` with `.name`, `.description`, `.content`, `.template`, `.updated`, `.uri`.

### {% llm %} — LLM Blocks

LLM-powered transformations:

```jinja
{% llm %}
Given: {{ ref('sources/metrics') }}
Identify the top 3 concerns.
{% endllm %}
```

With model and caching ID:

```jinja
{% llm model="sonnet" id="weekly-summary" %}
Summarize the week's activity.
{% endllm %}
```

### | extract — Extraction Filter

Extract specific information:

```jinja
{{ ref('sources/slack') | extract('action items') }}
{{ content | extract('key decisions', id='decisions') }}
```

### mcp_resource() — MCP Integration

Read resources from MCP servers:

```jinja
{{ mcp_resource('linear', 'linear://issue/ABC-123') }}
```

Configure servers in `colin.toml`:

```toml
[mcp.servers.linear]
url = "https://linear-mcp.example.com"

[mcp.servers.github]
command = "uvx"
args = ["mcp-server-github"]
```

Manage via CLI:

```bash
cbt mcp add linear --url https://...
cbt mcp add github --command uvx --args mcp-server-github
cbt mcp list
cbt mcp remove linear
```

## CLI

```bash
cbt init                 # Create new project
cbt run                  # Compile all documents
cbt run --force          # Force recompile everything
cbt run --dry-run        # Show what would compile
cbt status               # Show compilation status
cbt clean                # Remove outputs and manifest
cbt mcp list             # List MCP servers
```

## Configuration

`colin.toml`:

```toml
[project]
name = "my-project"
model-path = "models"    # Source documents
target-path = "target"   # Compiled output

[mcp.servers.example]
url = "https://..."
```

## Frontmatter

```yaml
---
name: My Document
description: A helpful description
custom_field: any metadata
---
```

## Caching

LLM calls are cached to avoid redundant API calls:

- **Auto IDs**: Hash-based, cache on identical input
- **Manual IDs**: Stable across prompt changes, receives previous output

```jinja
{{ content | extract('summary') }}              {# auto ID #}
{{ content | extract('summary', id='main') }}   {# manual ID #}
```

## Project Structure

```
my-project/
├── colin.toml           # Project configuration
├── models/              # Source .md files
│   ├── reports/
│   │   └── weekly.md
│   └── sources/
│       └── metrics.md
└── target/              # Compiled output (git-ignored)
    ├── compiled/
    └── manifest.json
```

## License

MIT
