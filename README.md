# Colin

***Context as code.***

Colin does for context what dbt did for SQL. It's a context compiler: pull data from scattered sources—files, APIs, databases, MCP servers—and use LLMs to synthesize, summarize, and transform it into Agent Skills and other formats agents can use. Declare dependencies with `ref()`, and Colin builds the graph, compiles in order, and recompiles only what changes.

Writing context by hand means copy-pasting from various sources, hoping nothing was missed, and watching it go stale. Colin keeps your context compiled, cached, and traceable—with full lineage from sources to outputs.

```bash
pip install colin
colin run
```

*Colin stands for **Co**ntext **Lin**eage — and also happens to be that perpetually helpful robot from The Hitchhiker's Guide to the Galaxy.*

---

## The Problem

Context is everywhere:

- **Local files** (Markdown, JSON, YAML)
- **MCP servers** (Linear, GitHub, Slack, databases)
- **Documentation** (Notion, Google Docs, wikis)
- **APIs** and data warehouses

Agents need this context synthesized and kept current. Today, someone writes a skill by hand, copy-pastes from various sources, hopes nothing was missed, and watches it go stale. There's no dependency tracking. No caching. No way to know what depends on what.

## How It Works

Write Markdown files with Jinja templating. Use `ref()` to pull in other documents, `| extract()` to pull out specific information with an LLM, and `{% llm %}` blocks for freeform synthesis.

Colin compiles them in dependency order, caches LLM calls, and recompiles only what's affected when sources change.

---

## Quick Start

Initialize a project:

```bash
colin init my-project
cd my-project
```

Create a source document `models/meeting-notes.md` that pulls from an MCP server:

```markdown
---
name: Meeting Notes
description: Recent meeting notes from the team
---

{# Pull notes from your Notion MCP server #}
{{ mcp_resource('notion', 'pages/meeting-notes') }}
```

Create a skill that extracts what matters in `models/project-status.md`:

```markdown
---
name: Project Status
description: Current project status for agents
---

# Project Status

**Last updated:** {{ ref('meeting-notes').updated }}

## Open Action Items
{{ ref('meeting-notes') | extract('action items and who owns them') }}

## Customer Risks
{{ ref('meeting-notes') | extract('customer risks or concerns') }}
```

Compile:

```bash
colin run
```

Colin discovers both documents, builds the dependency graph, compiles `meeting-notes` first, then `project-status` with the extracted content. LLM calls are cached—reruns are instant unless the source changes.

Output lands in `target/compiled/`.

**No LLM?** Use `ref()` directly for templating without AI:

```jinja
{{ ref('meeting-notes').content }}
```

---

## Core Concepts

### ref() — Dependency Resolution

Reference other documents. Colin builds the graph and compiles in order:

```jinja
{{ ref('context/team-roster') }}
```

Returns a `RefResult` with:

- `.content` — compiled output
- `.name` — from frontmatter
- `.description` — from frontmatter
- `.template` — raw source

### {% llm %} — LLM Transformations

LLM-powered synthesis:

```jinja
{% llm %}
Given: {{ ref('sources/metrics') }}
Identify the top 3 concerns.
{% endllm %}
```

With model selection:

```jinja
{% llm model="anthropic:claude-sonnet-4-5" %}
Summarize the week's activity.
{% endllm %}
```

### | extract — Focused Extraction

Pull specific information from content:

```jinja
{{ ref('sources/slack') | extract('action items from this week') }}
{{ ref('sources/calls') | extract('feature requests mentioned') }}
```

### Caching

LLM calls are cached based on inputs:

- **Auto caching**: Same input + same prompt = cached result
- **Manual IDs**: Stable across prompt changes, receives previous output

```jinja
{{ content | extract('summary') }}                    {# auto cache #}
{{ content | extract('summary', id='main-summary') }} {# manual ID #}
```

Manual IDs let you iterate on prompts without regenerating everything.

---

## CLI

```bash
colin init [name]          # Create new project
colin run                  # Compile all documents
colin run --force          # Recompile everything
colin run --dry-run        # Show what would compile
colin status               # Show project status
colin clean                # Remove outputs and cache
```

## Configuration

`colin.toml`:

```toml
[project]
name = "my-project"
model-path = "models"    # Source documents
target-path = "target"   # Compiled output
```

### MCP Servers

Connect to MCP servers for external data:

```toml
[mcp.servers.linear]
url = "https://linear-mcp.example.com"

[mcp.servers.github]
command = "uvx"
args = ["mcp-server-github"]
```

```bash
colin mcp add linear --url https://...
colin mcp list
```

## Project Structure

```
my-project/
├── colin.toml           # Configuration
├── models/              # Source documents
│   ├── sources/
│   │   └── metrics.md
│   └── summaries/
│       └── weekly.md
└── target/              # Compiled output
    ├── compiled/
    └── manifest.json    # Lineage + cache
```

---

## Coming Soon

- **MCP resource integration** — `{{ mcp_resource('linear', 'projects') }}` to pull live data
- **Watch mode** — Recompile on file changes
- **Cost tracking** — Per-document LLM cost attribution

---

## Part of Prefect's Context Layer

Colin is built by [Prefect](https://prefect.io) as part of our mission to deliver the right context to agents at the right time. It connects to [MCP](https://modelcontextprotocol.io) for data access and produces [Agent Skills](https://github.com/anthropics/anthropic-cookbook/tree/main/misc/prompt_caching) for delivery.

Apache 2.0
