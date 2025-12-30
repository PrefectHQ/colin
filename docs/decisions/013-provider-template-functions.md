# ADR 013: Provider Template Functions

**Status**: Accepted
**Date**: 2025-01-06

## Context

Providers need to expose template functions (beyond `read()`) while supporting multiple instances of the same provider type. MCP is a primary example: users may configure multiple MCP servers and expect a single function name (e.g., `resource`) to work across instances.

We also need a configuration format that supports nested provider config tables without ambiguity.

## Decision

### Template Namespace

Provider functions live under a unified namespace:

```
providers.<type>.<name>.<function>(...)
```

Default instances (no `name`) may be called with shorthand:

```
providers.<type>.<function>(...)
```

`mcp` is always aliased to `providers.mcp`, and `extract` is aliased to `providers.llm.extract`.

### Configuration Format

Provider instances are defined using array-of-tables:

```toml
[[providers.s3]]
bucket = "main"

[[providers.s3]]
name = "dev"
bucket = "dev"

[[providers.mcp]]
name = "github"
command = "uvx"
args = ["mcp-server-github"]
```

Each entry supports:
- `name`: optional instance name (default instance when omitted)
- `scheme-suffix`: optional override for the URI scheme suffix (defaults to `name`)

### Schemes

Schemes are derived as:
- Default instance: `provider_type`
- Named instance: `provider_type.<scheme-suffix>`

Example: `providers.s3.dev` -> `s3.dev://...`

### Provider Function Returns

Providers register functions via `Provider.get_functions()`. Functions can return:
- `str`: returned as-is (no dependency)
- `Reference`: converted to `RefResult` and tracked as a ref
- `RefResult`: tracked as a ref

This keeps dependency tracking centralized in the template wrapper while allowing providers to emit referenceable results.

## Consequences

- `mcp_resource()` and `mcp_prompt()` are replaced by `mcp.<server>.resource()` and `mcp.<server>.prompt()`
- Provider configuration is always array-of-tables
- Multiple provider instances coexist without function name collisions
