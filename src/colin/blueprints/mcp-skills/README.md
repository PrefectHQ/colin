# MCP Skill Generator

Generate Claude Code skills from any MCP server automatically.

## Quick Start

1. **Add your MCP server** with the name `source`:
   ```bash
   colin mcp add source "npx -y @your-org/mcp-server"
   ```

   Or for a remote server:
   ```bash
   colin mcp add source --url http://localhost:9000/mcp
   ```

2. **Generate skills**:
   ```bash
   colin run
   ```

Skills are written to `~/.claude/skills/` by default (Claude Code's user skill directory).

## Configuration

Edit `colin.toml` to customize:

```toml
[vars]
# Override the skill folder name (defaults to server name)
mcp_provider_name = "my-custom-name"

# Disable script generation
generate_scripts = false
```

## What Gets Generated

```
<server-name>/
├── SKILL.md           # Main skill file with server overview
├── greet.md           # Tool documentation
├── calculate.md       # Tool documentation
└── scripts/
    ├── greet.py       # Executable wrapper (optional)
    └── calculate.py
```
