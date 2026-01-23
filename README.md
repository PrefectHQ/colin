<div align="center">

<picture>
  <img width="550" alt="Colin Logo" src="docs/assets/logos/c-watercolors.png">
</picture>

# Colin

**A context engine that keeps agent skills fresh.**

</div>

---

Colin is a context engine. Write templates that reference live sources—GitHub, Linear, Notion, HTTP endpoints—and other documents. Colin compiles them, tracks dependencies, and rebuilds only what's stale.

```markdown
---
name: project-overview
description: Current state of the project
---

# Project Overview

{{ colin.github.file('PrefectHQ/prefect', 'README.md').content | llm_extract('what is this project and what are its key features') }}

## Contributing

{{ colin.github.file('PrefectHQ/prefect', 'CONTRIBUTING.md').content }}

## Recent Activity

{% for issue in colin.github.issues('PrefectHQ/prefect', state='open', limit=5) %}
- [#{{ issue.number }}]({{ issue.url }}): {{ issue.title }}
{% endfor %}
```

Run `colin run`. Colin fetches the README and contributing guide from GitHub, lists recent issues, and writes the compiled skill. Run it again tomorrow—if nothing changed upstream, nothing rebuilds. If the README was updated, Colin detects the new commit and recompiles.

## Install

```bash
pip install colin-py
```

## Documentation

Full documentation at [colin.prefect.io/docs](https://colin.prefect.io/docs).

## Quick Start

```bash
colin init my-skill
cd my-skill
```

Edit `models/hello.md` or create new documents in `models/`. Each document can reference others with `ref()` and pull from external sources.

```bash
colin run
```

Colin compiles your documents to `output/`. Update a source file and run again—only affected documents recompile.

## Output to Claude Code

Configure Colin to write directly to Claude Code's skills folder:

```toml
[project.output]
target = "claude-skill"
scope = "user"
```

Skills appear in `~/.claude/skills/` and become available immediately.

## How It Works

When Colin compiles a document, it records what sources were used and their versions—commit SHAs for GitHub files, timestamps for HTTP resources, version identifiers for MCP resources. This information is stored in a manifest alongside the compiled output.

On subsequent runs, Colin checks the manifest against current source versions. Documents whose sources haven't changed skip compilation entirely. When a source does change, Colin recompiles the affected document and any documents that depend on it.

LLM calls are cached separately by input hash. If a document recompiles but the input to an LLM block is unchanged, the cached LLM response is reused.

## About the Name

Colin stands for **Co**ntext **Lin**eage. It's also a nod to [Colin the robot](https://hitchhikers.fandom.com/wiki/Colin) from the Hitchhiker's Guide to the Galaxy—a security robot who feels genuinely delighted whenever he's being helpful.

---

Colin is built with 💙 by [Prefect](https://prefect.io).
