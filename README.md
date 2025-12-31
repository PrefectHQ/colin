
<div align="center">

<picture>
  <img width="550" alt="Colin Logo" src="docs/assets/logos/c-watercolor-waves.jpeg">
</picture>

</div>

# Colin

***Context as code.***

Colin is a context engine for building context pipelines—extract from sources, transform with LLMs, load to outputs. Write templates that reference other documents, pull from GitHub, Linear, Slack, databases via MCP. When sources change, Colin recompiles. Your context and skills stay fresh automatically.

```bash
pip install colin
colin run
```

*Colin stands for **Co**ntext **Lin**eage — and also happens to be that perpetually helpful robot from The Hitchhiker's Guide to the Galaxy.*

---

## The Problem

Your agent's context is scattered everywhere—project trackers, customer calls, documentation, databases. Someone writes it up as a skill or prompt. A month later:

- The deployment process changed
- Staging got renamed
- The API added new endpoints
- Q3 priorities are now Q4 priorities

The context is stale. The agent is wrong. Nobody noticed.

Manual maintenance doesn't scale. There's no dependency tracking, no way to know what depends on what, no alert when upstream sources change.

## How Colin Works

Write markdown templates that reference live data. Colin builds the dependency graph and compiles in order:

```markdown
---
name: Project Status
---

# Current Sprint

{{ mcp.linear.resource('projects/current-sprint').content }}

## Key Risks

{{ ref('team/capacity') | extract('blockers and concerns') }}

## Customer Context

{% llm %}
Summarize recent customer feedback relevant to this sprint:

{{ mcp.intercom.resource('conversations/last-7-days').content }}
{% endllm %}
```

When you run `colin run`:

1. Colin resolves dependencies in topological order
2. Checks if sources changed (documents, MCP resources, etc.)
3. Recompiles only what's affected
4. Runs LLM calls to synthesize and extract (cached by input)
5. Outputs compiled context to `target/`

When any source updates, everything that depends on it recompiles automatically. Like dbt's `ref()`, but for context.

---

## Core Primitives

### ref() — Connect Documents

Reference other documents. Colin builds the graph and compiles in order:

```jinja
{{ ref('company/overview').content }}
```

When `company/overview` changes, everything that references it recompiles.

### extract() — Pull What Matters

LLM extracts specific information from content:

```jinja
{{ ref('meeting-notes') | extract('action items and owners') }}
{{ ref('customer-calls') | extract('feature requests mentioned') }}
```

### http.get() — Fetch Web Content

Pull content directly from URLs:

```jinja
{{ http.get('https://api.example.com/data.json') }}
{{ http.get('example.com/api/users') }}  {# https:// added automatically #}
```

### mcp.server.resource() — Fetch Live Data

Pull from external sources via MCP:

```jinja
{{ mcp.linear.resource('projects/engineering').content }}
{{ mcp.github.resource('repo://org/repo/README.md').content }}
```

### {% llm %} — Synthesize Across Sources

Freeform LLM synthesis:

```jinja
{% llm %}
Compare these two analyses and identify trends:

{{ ref('q3-report').content }}
{{ ref('q4-report').content }}
{% endllm %}
```

---

## Quick Start

```bash
colin init my-project
cd my-project
```

Create `models/company.md`:

```markdown
---
name: Company Overview
---

We build developer tools for CI/CD pipelines.
```

Create `models/pitch.md`:

```markdown
---
name: Sales Pitch
---

# About Us

{{ ref('company').content }}

# Why Choose Us

{{ ref('company') | extract('key selling points') }}
```

Compile:

```bash
colin run
```

Colin compiles `company` first (no dependencies), then `pitch` (depends on `company`). Output lands in `target/compiled/`. Change `company.md` and `pitch.md` recompiles automatically.

---

## Use Cases

**Agent Skills**: Context your agent loads on-demand—stays current as sources change.

**System Prompts**: Dynamic prompts that update automatically when team info, processes, or priorities shift.

**Team Briefings**: Status reports assembled from project trackers, synthesized by LLMs.

**Documentation**: Internal docs that pull from multiple sources and never go stale.

---

## Configuration

`colin.toml`:

```toml
[project]
name = "my-context"
model-path = "models"
target-path = "target"

[[providers.llm]]
model = "anthropic:claude-sonnet-4-5"

[[providers.mcp]]
name = "linear"
command = "npx"
args = ["@anthropic/mcp-server-linear"]

[[providers.mcp]]
name = "github"
command = "uvx"
args = ["mcp-server-github"]
```

## CLI

```bash
colin init [name]      # Create new project
colin run              # Compile all documents
colin run --no-cache   # Recompile everything
colin status           # Show project status
colin clean            # Remove outputs and cache
colin mcp              # Manage MCP servers
```

---

## Part of Prefect's Context Layer

Colin is built by [Prefect](https://prefect.io) as part of our mission to deliver the right context at the right time.
