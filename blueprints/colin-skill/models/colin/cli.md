---
name: colin-cli
description: Colin CLI commands reference
colin:
  template: false
---

# CLI Commands

## colin init

Create a new project:

```bash
colin init                    # In current directory
colin init my-project         # Create new directory
colin init -b mcp-skills      # Use a blueprint
```

## colin run

Compile the project:

```bash
colin run                     # Compile changed documents
colin run --no-cache          # Recompile everything
colin run --output ./dist     # Override output directory
colin run --var key=value     # Set a variable
colin run --ephemeral         # Don't write to .colin/ cache
```

## colin update

Update an output directory from its source:

```bash
colin update                  # Update current directory
colin update ~/.claude/skills # Update specific directory
```

Reads the manifest to find the source project and recompiles.

## colin clean

Remove stale files:

```bash
colin clean                   # Clean output directory
colin clean --all             # Also clean .colin/compiled/
colin clean -y                # Skip confirmation
```

## colin skills update

Update all Colin-managed skills:

```bash
colin skills update                    # Update ~/.claude/skills/
colin skills update ~/.codex/skills/   # Update specific directory
```

Finds all skill directories with Colin manifests and updates them in parallel.

## colin mcp

Manage MCP server connections:

```bash
colin mcp add github uvx mcp-server-github
colin mcp list
colin mcp test github
colin mcp remove github
```
