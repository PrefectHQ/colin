# ADR 005: ref() Returns Resource Objects

**Status**: Accepted
**Date**: 2024-12-27
**Updated**: 2026-01-01

## Context

The original design was vague about what `ref()` returns, simply saying "returns content." But documents have metadata beyond just content:
- Name and description (from frontmatter)
- A way to re-fetch for staleness checking
- Version information for change detection

## Decision

`ref()` returns Resource objects. The specific type depends on the input:

**For string paths** (project refs):
```python
class ProjectResource(Resource):
    path: str                # Relative path (e.g., "greeting.md")
    name: str                # From frontmatter or derived from path
    description: str | None  # From frontmatter
    # Inherited from Resource:
    # .content: str          # Compiled output
    # .ref() -> Ref          # For re-fetching
    # .version: str          # Content hash

    def __str__(self) -> str:
        return self.content
```

**For provider resources** (S3, MCP, HTTP, etc.):
```python
# ref() returns the same Resource type, unchanged
ref(colin.s3.prod.get("config.json"))  # Returns S3Resource
ref(colin.mcp.github.resource("..."))   # Returns MCPResource
```

Usage:
```jinja
{{ ref("context/foo") }}              {# Outputs content via __str__ #}
{{ ref("context/foo").name }}         {# Access name #}
{{ ref("context/foo").version }}      {# Access version #}

{% set cfg = ref(colin.s3.prod.get("config.json")) %}
{{ cfg.content }}                     {# S3 content #}
```

## Rationale

1. **Rich metadata**: Templates can access more than just content
2. **Ergonomic**: `__str__` means `{{ ref() }}` works naturally in templates
3. **Unified model**: All refs are Resources with `.ref()` for staleness tracking
4. **Type safe**: Specific Resource subclasses for each provider

See [ADR 017](017-resource-and-ref-architecture.md) for the full Resource/Ref architecture.

## Consequences

- `ref()` returns `ProjectResource` for string paths
- `ref()` passes through provider Resources unchanged (just tracks them)
- All Resources have `.content`, `.ref()`, `.version`
- Staleness checking uses `resource.ref()` to replay and compare versions
