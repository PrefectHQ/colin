# ADR 013: Provider Template Functions

**Status**: Accepted
**Date**: 2025-01-06
**Updated**: 2025-01-06

## Context

Providers need to expose template functions (beyond `read()`) while supporting multiple instances of the same provider type. MCP is a primary example: users may configure multiple MCP servers and expect a single function name (e.g., `resource`) to work across instances.

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

Provider functions return domain objects, not `RefResult`. Domain objects implement the `Referenceable` protocol:

```python
@runtime_checkable
class Referenceable(Protocol):
    @property
    def uri(self) -> str: ...
    def to_ref_result(self) -> RefResult: ...
```

MCP provider returns `MCPResource` and `MCPPrompt`:

```python
@dataclass
class MCPResource:
    uri: str
    content: str
    name: str
    description: str | None = None

    def to_ref_result(self) -> RefResult:
        return RefResult(..., source=self)
```

### Dependency Tracking

Provider functions do NOT automatically track dependencies. To track a dependency, wrap with `ref()`:

```jinja
{# Not tracked - returns MCPResource #}
{{ colin.mcp.github.resource('repo://...').content }}

{# Tracked - returns RefResult #}
{{ ref(colin.mcp.github.resource('repo://...')).content }}
```

The `ref()` function accepts both URI strings and `Referenceable` objects. For Referenceable objects, it calls `to_ref_result()` and records the dependency.

### Accessing Original Objects

`RefResult.source` preserves the original domain object:

```jinja
{% set r = ref(colin.mcp.github.resource('repo://...')) %}
{{ r.content }}        {# RefResult.content #}
{{ r.source.uri }}     {# MCPResource.uri #}
```

## Consequences

- Provider functions return domain objects (MCPResource, MCPPrompt)
- `ref()` accepts `str | Referenceable`
- Dependency tracking is explicit via `ref()` wrapper
- `RefResult.source` provides escape hatch to original object
- `colin.mcp.<server>.resource()` and `colin.mcp.<server>.prompt()` replace old functions
