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
name: team-status
description: Current state of platform team work
colin:
  cache:
    expires: 1d
---

# Team Status

## In Progress

{% for issue in colin.linear.issues(team='Platform', state='In Progress') %}
- {{ issue.identifier }}: {{ issue.title }} ({{ issue.assignee }})
{% endfor %}

## Summary

{{ ref('team/weekly-notes.md').content | llm_extract('key blockers and priorities') }}
```

Run `colin run`. Colin fetches the Linear issues, resolves the reference to your weekly notes, extracts blockers via LLM, and writes the compiled skill. Run it again tomorrow—if nothing changed upstream, nothing rebuilds. The `expires: 1d` ensures time-sensitive content stays fresh.

## Install

```bash
pip install colin-py
```

## Documentation

Full documentation at [colin.prefect.io](https://colin.prefect.io).

## Quick Start

The fastest way to get started is with the quickstart blueprint, which builds a skill from Colin's own documentation:

```bash
colin init using-colin -b quickstart
cd using-colin
colin run
```

The compiled skill contains the Colin quickstart—pulled live from GitHub. When we update the docs, your agent's knowledge updates too.

## Output to Claude Code

Configure Colin to write directly to Claude Code's skills folder:

```toml
[project.output]
target = "claude-skill"
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
