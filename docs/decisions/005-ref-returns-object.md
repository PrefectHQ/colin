# ADR 005: ref() Returns Structured Object

**Status**: Accepted
**Date**: 2024-12-27
**Updated**: 2025-01-06

## Context

The original design was vague about what `ref()` returns, simply saying "returns content." But documents have metadata beyond just content:
- Name and description (from frontmatter)
- When it was last compiled
- The original template source

## Decision

`ref()` returns a `RefResult` object with structured fields:

```python
class RefResult:
    name: str                # From frontmatter or derived from URI
    description: str | None  # From frontmatter
    content: str             # The compiled output
    template: str            # The raw uncompiled source
    updated: datetime        # When it was last compiled
    uri: str                 # The ref URI
    source: object | None    # Original domain object (MCPResource, etc.)

    def __str__(self) -> str:
        return f"Ref({self.uri!r})"
```

The `__str__()` method returns a placeholder to prevent accidentally dumping large content. Use `.content` explicitly:
```jinja
{{ ref('context/foo').content }}      {# Outputs content #}
{{ ref('context/foo').name }}         {# Access name #}
{{ ref('context/foo').updated }}      {# Access timestamp #}
```

## Rationale

1. **Rich metadata**: Templates can access more than just content
2. **Backward compatible**: `__str__` means `{{ ref() }}` works as expected
3. **Extensible**: Future fields can be added to RefResult
4. **Type safe**: Structured object vs. untyped dict

## Consequences

- `ref()` must construct RefResult with all fields populated
- Documents must have compiled output available (handled by topo sort)
- Metadata comes from manifest and frontmatter
