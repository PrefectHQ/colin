# ADR 013: Provider Template Functions

**Status**: Accepted
**Date**: 2025-12-30
**Updated**: 2026-01-01

## Context

Providers need to expose template functions while supporting multiple instances of the same provider type. MCP is a primary example: users may configure multiple MCP servers and expect a single function name (e.g., `resource`) to work across instances.

We also need a configuration format that supports nested provider config tables without ambiguity.

## Decision

### Template Namespace

Provider functions live under the `colin` namespace (see [ADR 015](./015-provider-namespace-design.md)):

```
colin.<type>.<name>.<function>(...)
```

No root-level aliases are provided—all providers are accessed via `colin.*`.

### Configuration Format

Provider instances are defined using array-of-tables:

```toml
[[providers.mcp]]
name = "github"
command = "uvx"
args = ["mcp-server-github"]

[[providers.mcp]]
name = "linear"
command = "npx"
args = ["@linear/mcp-server"]
```

Each MCP entry requires a `name`. This name becomes the accessor in templates.

### Provider Function Returns

Provider functions return `Resource` objects (see [ADR 017](017-resource-and-ref-architecture.md)):

```python
class Resource:
    content: str      # The fetched content
    def ref(self) -> Ref: ...   # Replay instructions for staleness
    version: str      # For change detection (hash, ETag, etc.)
```

Each provider defines its own Resource subclass:

```python
class MCPResource(Resource):
    uri: str
    name: str
    description: str | None = None
```

### Dependency Tracking

Provider functions can auto-track via the `watch` parameter (default varies by provider):

```jinja
{# Auto-tracked (default for most providers) #}
{{ colin.mcp.github.resource('repo://...') }}

{# Explicitly not tracked #}
{{ colin.http.get('https://volatile.example.com', watch=False) }}

{# Explicit tracking via ref() #}
{{ ref(colin.s3.prod.get("config.json")) }}
```

The `ref()` function accepts Resource objects and registers their Ref for staleness checking.

### Accessing Resource Properties

Resources have `.content` for the fetched content and provider-specific properties:

```jinja
{% set issue = colin.mcp.github.resource('issue://123') %}
{{ issue.content }}        {# The issue content #}
{{ issue.uri }}            {# MCPResource.uri #}
{{ issue.name }}           {# MCPResource.name #}
```

## Consequences

- Provider functions return Resource subclasses (MCPResource, S3Resource, etc.)
- `ref()` accepts `str | Resource`
- Dependency tracking is controlled via `watch` parameter or `ref()` wrapper
- Resources have `.content`, `.ref()`, `.version` plus provider-specific fields
- `colin.mcp.<server>.resource()` and similar methods return Resources
