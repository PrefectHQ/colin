# MCP Example

Demonstrates pulling data from MCP servers into Colin templates.

## What It Shows

- Configuring an MCP server in `colin.toml`
- Fetching MCP resources with `colin.mcp.<name>.resource()`
- Fetching MCP prompts with `colin.mcp.<name>.prompt()`

## Files

- `mcp_server.py` - A simple FastMCP server with a greeting resource and summarize prompt
- `models/greeting.md` - Template that pulls from the MCP server
- `colin.toml` - Configures the MCP server connection

## Run It

```bash
cd examples/mcp
colin run
```

Colin starts the MCP server, fetches the resource and prompt, and compiles the output.

## MCP Provider

Any MCP server you configure becomes available as `colin.mcp.<name>`:

```toml
[[providers.mcp]]
name = "demo"
command = "uvx"
args = ["--with", "fastmcp", "fastmcp", "run", "mcp_server.py"]
```

Then in templates:

```jinja
{{ colin.mcp.demo.resource('demo://greeting/World') }}
{{ colin.mcp.demo.prompt('summarize', style='detailed') }}
```

Colin tracks MCP resource versions—when upstream data changes, affected documents recompile.
