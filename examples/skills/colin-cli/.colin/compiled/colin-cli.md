# Colin CLI Guide

Colin is a context compiler that transforms interconnected documents into compiled outputs for AI agents.

## Core Commands

### `colin run`
Compile a project. Run from a directory with `colin.toml`:
```bash
colin run              # Compile current project
colin run --quiet      # Suppress progress output
colin run --no-cache   # Force recompile everything
colin run --output ./dist  # Override output directory
```

### `colin update`
Update outputs from their source project. Run from an output directory (one with `.colin-manifest.json`):
```bash
colin update                    # Update current directory
colin update ~/.claude/skills/my-skill  # Update specific output
colin update --no-cache         # Force full rebuild
```

### `colin skills update`
Update all Colin-managed skills in a directory:
```bash
colin skills update             # Update ~/.claude/skills
colin skills update ./my-skills # Update custom directory
```

### `colin init`
Create a new Colin project:
```bash
colin init           # Initialize in current directory
colin init ./new-project  # Initialize in new directory
```

### `colin clean`
Remove stale files from output:
```bash
colin clean          # Clean output/ only
colin clean --all    # Clean output/ and .colin/compiled/
```

## MCP Server Management

### `colin mcp add`
Add an MCP server to your project:
```bash
# HTTP server
colin mcp add sentry https://mcp.sentry.dev/sse

# Stdio server
colin mcp add github uvx mcp-server-github

# With environment variables
colin mcp add airtable npx airtable-mcp -e AIRTABLE_API_KEY=xxx
```

### `colin mcp list`
List configured MCP servers:
```bash
colin mcp list
```

### `colin mcp test`
Test connection to an MCP server:
```bash
colin mcp test github
```

### `colin mcp remove`
Remove an MCP server:
```bash
colin mcp remove github
```

## Common Workflows

**Create and install a skill:**
```bash
cd my-skill-project
colin run --output ~/.claude/skills/my-skill
```

**Update all installed skills:**
```bash
colin skills update
```

**Iterate on a skill:**
```bash
# Edit source files, then:
colin update ~/.claude/skills/my-skill
```