<div align="center">

<picture>
  <img width="550" alt="Colin Logo" src="docs/assets/logos/c-watercolor-waves.jpeg">
</picture>

# Colin

**The context engine that keeps agent knowledge fresh.**

</div>

---

Context goes stale. Colin keeps it fresh.

Write context files that reference each other, pull from MCP servers, fetch data from APIs, and extract insights with LLMs. Colin's context engine resolves dependencies and only recompiles affected documents whenever sources change.

```markdown
---
name: Deployment Guide
---

# How to Deploy

{{ ref('infrastructure/environments').content }}

## Current Process

{{ colin.mcp.github.resource('repo://acme/platform/docs/DEPLOYING.md').content }}

## Recent Issues

{{ colin.mcp.pagerduty.resource('incidents/last-30-days') | extract('deployment-related incidents and their resolutions') }}
```

Run `colin run`. Colin fetches your infrastructure doc, pulls the latest deployment guide from GitHub, queries PagerDuty for recent incidents, uses an LLM to extract the deployment-related ones, and compiles it all into a single document.

Tomorrow, someone updates the GitHub deployment guide. Next time you run `colin run`, Colin knows—and recompiles. The PagerDuty incidents from last month expire; Colin fetches fresh ones. Your infrastructure doc changes; everything that references it recompiles too.

You write templates. Colin keeps them true.

*Colin stands for **Co**ntext **Lin**eage — and also happens to be that perpetually helpful robot from The Hitchhiker's Guide to the Galaxy.*

---

## Install

```bash
pip install colin
```

---

## The Idea

Every piece of context has sources. A deployment guide references infrastructure docs, GitHub repos, incident history. A sales pitch references product docs, pricing, customer testimonials. These sources change constantly.

Static files drift. Templates stay true.

Colin templates are Jinja2 markdown. A few things they can do:

- **Reference other templates** — `ref('infrastructure/envs')` creates a dependency. When `envs` changes, everything referencing it recompiles.

- **Pull from MCP servers** — `colin.mcp.github.resource('repo://...')` fetches live data. Any MCP server works: Linear, Slack, databases, your internal tools.

- **Fetch from HTTP** — `colin.http.get('https://...')` pulls from APIs.

- **Extract with LLMs** — `content | extract('the key points')` uses an LLM to pull specific information from any content.

- **Synthesize with LLMs** — `{% llm %}...{% endllm %}` sends content to an LLM for freeform processing.

When you run `colin run`:

1. Colin parses your templates and discovers dependencies—no declarations needed
2. Sorts the dependency graph and compiles in order
3. Checks which sources changed since last run
4. Recompiles only affected documents
5. Caches LLM calls by input hash—same input, no redundant API calls

The result: context that's always fresh, compiled from your actual sources of truth.

---

## Quick Start

```bash
colin init my-context
cd my-context
```

Create `models/team.md`:

```markdown
---
name: Team Overview
---

# Engineering Team

We're a team of 12 engineers working on developer tools.

## Current Focus
- API v2 migration
- Performance improvements
- Customer onboarding flow
```

Create `models/standup.md`:

```markdown
---
name: Standup Context
---

# Daily Standup

## Team
{{ ref('team').content }}

## Active Sprint
{{ colin.mcp.linear.resource('projects/current-sprint').content }}

## Blockers
{{ colin.mcp.linear.resource('projects/current-sprint') | extract('blocked tickets and why') }}

## Yesterday's Deploys
{{ colin.mcp.github.resource('repo://acme/api/deployments/yesterday') | extract('what shipped and any issues') }}
```

```bash
colin run
```

Colin compiles `team` first (no dependencies), then `standup` (depends on `team` plus Linear and GitHub data). Output lands in `output/`.

Update `team.md`—add a new engineer, change the focus areas. Run `colin run` again. Both documents recompile because `standup` depends on `team`.

Sprint changes in Linear? Those sections recompile. Yesterday's deploys update in GitHub? That section recompiles. Team doc stays the same? It's skipped entirely.

---

## Templates

### ref() — Reference Other Documents

```jinja
{{ ref('company/overview').content }}

{{ ref('company/overview').name }}

{{ ref('company/overview').description }}
```

Creates a dependency edge. When the referenced document changes, this one recompiles. Access `.content` for the compiled output, or `.name` and `.description` from frontmatter.

Without `.content`, resources render as their content automatically:

```jinja
{{ ref('company/overview') }}
```

### extract() — LLM Extraction

```jinja
{{ ref('meeting-notes') | extract('action items with owners') }}

{{ colin.mcp.slack.resource('channels/support/today') | extract('urgent customer issues') }}

{{ colin.http.get('https://api.example.com/logs') | extract('errors in the last hour') }}
```

Pipe any content to `extract()` with a prompt. The LLM pulls out exactly what you asked for. Results are cached—same input and prompt means no redundant API calls.

### mcp — Live Data from MCP Servers

```jinja
{{ colin.mcp.linear.resource('projects/engineering').content }}

{{ colin.mcp.github.resource('repo://acme/api/README.md').content }}

{{ colin.mcp.slack.resource('channels/engineering/recent').content }}

{{ colin.mcp.postgres.resource('query/active-users').content }}
```

Any MCP server you configure becomes a source. Colin tracks versions—when upstream data changes, affected documents recompile.

### http.get() — Fetch URLs

```jinja
{{ colin.http.get('https://api.example.com/status.json') }}

{{ colin.http.get('internal.company.com/config') }}
```

### {% llm %} — Freeform LLM Processing

```jinja
{% llm %}
You have two quarterly reports. Identify trends, concerns, and recommendations.

## Q3
{{ ref('reports/q3').content }}

## Q4
{{ ref('reports/q4').content }}
{% endllm %}
```

Everything inside the block goes to the LLM. The block renders as the response. Cached by input hash.

---

## Dependency Tracking

Colin discovers dependencies by parsing your templates. Write `ref('thing')` and the dependency exists—no config file, no declarations.

```
models/
  team.md
  sprint.md        ← refs team
  standup.md       ← refs team, sprint
  weekly-report.md ← refs standup, sprint
```

Change `team.md` and everything above it in the graph recompiles. Change `weekly-report.md` and only it recompiles—nothing depends on it.

For external resources (MCP, HTTP), Colin tracks versions automatically. When you fetch from Linear or GitHub, Colin remembers the version. Next run, it checks if the version changed. If so, documents using that resource recompile.

---

## Configuration

`colin.toml`:

```toml
[project]
name = "my-context"
model-path = "models"
output-path = "output"

[[providers.llm]]
model = "anthropic:claude-sonnet-4-5"

[[providers.mcp]]
name = "linear"
command = "npx"
args = ["@linear/mcp-server"]

[[providers.mcp]]
name = "github"
command = "uvx"
args = ["mcp-server-github"]

[[providers.mcp]]
name = "slack"
command = "npx"
args = ["@anthropic/mcp-server-slack"]
```

MCP servers are configured once, then available as `colin.mcp.<name>` in all templates.

---

## Frontmatter

```yaml
---
name: My Document
description: What this document provides

colin:
  output:
    format: markdown              # markdown, json, yaml
    path: reports/summary.md      # custom output location (optional)
    publish: true                 # copy to output/ (optional)
  cache:
    policy: auto                  # auto, always, never
    expires: 1d                   # optional time-based expiration
---
```

### Output Configuration

**format** — Transformation to apply:
- `markdown` — Pass through as markdown (default)
- `json` — Convert markdown headings to JSON object
- `yaml` — Convert markdown headings to YAML

**path** — Custom output location relative to `output/`. Supports subdirectories. If omitted, uses the source filename with the format's extension.

**publish** — Whether to copy the compiled artifact to `output/`. Set `false` to keep the file in `.colin/compiled/` only (useful for helper templates). Default is `true`.

### Private Files

Files can be kept out of `output/` in two ways:

1. **Naming convention**: Prefix the filename or any parent directory with `_`. These files compile to `.colin/compiled/` but don't publish to `output/`.

   ```
   models/_helpers/formatting.md    → private
   models/_config.md                → private
   models/public.md                 → published
   ```

2. **Explicit config**: Set `publish: false` in frontmatter to override the naming convention.

Private files are accessible via `ref().content` but `ref().path` raises an error—you can include their content, but you can't link to files that won't exist in `output/`.

### Cache Policies

- `auto` — Rebuild when any source changes (default)
- `always` — Only rebuild with `--no-cache`
- `never` — Always rebuild

**Expiration:** Force rebuild after a duration regardless of source changes. Useful for content that should refresh periodically.

---

## CLI

```bash
colin init [name]      # Create a new project
colin run              # Compile all documents
colin run --no-cache   # Force full recompile
colin clean            # Remove outputs and cache
```

---

## Agent Skills

Agent skills are instruction manuals for agents—markdown files that teach them how to do things like deploy code, integrate with APIs, or follow your team's workflows. Tools like Claude Code, Cursor, and Codex can dynamically load skills to understand your specific context.

A skill needs a `name` and `description` in its frontmatter. The description tells the agent when to use the skill.

Skills have the same problem as any documentation: they go stale. Someone writes a skill describing your deployment process, then six months later you've migrated CI systems and renamed environments. The skill is wrong. The agent gives bad advice.

Colin compiles skills from live sources. Instead of a static file, you write a template that pulls from your actual infrastructure docs, your GitHub repos, your incident history. The skill stays fresh because it's compiled from fresh sources.

```markdown
---
name: deployment-process
description: How to deploy code to staging and production environments
---

# Deployment

{{ ref('infrastructure/environments').content }}

## Steps

{{ colin.mcp.github.resource('repo://acme/platform/docs/DEPLOY.md').content }}

## Recent Issues

{{ colin.mcp.pagerduty.resource('incidents/deploy-related/last-30d') | extract('what went wrong and how it was fixed') }}
```

Run `colin run` and drop the compiled output into your skills directory. Your agent always has current knowledge.

---

## Part of Prefect's Context Layer

Colin is built with 💙 by [Prefect](https://prefect.io) as part of our mission to deliver the right context at the right time.
