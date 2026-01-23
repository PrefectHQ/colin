# ADR 015: Provider Namespace Design

**Status**: Accepted
**Date**: 2026-01-01

## Context

Colin's providers are currently exposed to templates under the `providers` namespace (e.g., `providers.mcp.github.resource()`). This is verbose and bureaucratic. We also artificially elevate some providers like `mcp` and `llm` to the root namespace for convenience, creating inconsistency.

As we add more providers (file, S3, HTTP, future integrations like dbt/SQL), we need a clear, consistent namespace design that:
- Is concise and readable in templates
- Scales to many providers without collision
- Clearly indicates which methods are user-facing vs internal
- Handles providers that expose multiple methods (not just `read()`)

## Decision

### 1. Use `colin` as the Provider Namespace

Replace `providers` with `colin`:

```jinja
{# Before #}
{{ providers.mcp.github.resource('repo://...') }}
{{ providers.llm.extract(content, 'summary') }}
{{ providers.file.read('/path/to/file') }}

{# After #}
{{ colin.mcp.github.resource('repo://...') }}
{{ colin.llm.extract(content, 'summary') }}
{{ colin.file.read('/path/to/file') }}
```

**Rationale:**
- Self-explanatory and branded
- Reads naturally: "Colin reads file", "Colin connects to MCP"
- Shorter than `providers` (5 chars vs 9)
- More discoverable for new users than abstract names like `ctx` or `io`

### 2. No Top-Level Shortcuts

With `colin` as the namespace, we no longer need to elevate providers to root level. `colin.llm` and `colin.mcp` are ergonomic enough:

```jinja
{# These feel good as-is #}
{{ colin.llm.extract(content, 'summary') }}
{{ colin.mcp.github.resource('repo://...') }}
{{ colin.file.read('/data.json') }}
{{ colin.s3.read('s3://bucket/key') }}
```

This eliminates the inconsistency of having some providers at root and others nested.

### 3. Underscore Convention for Internal Methods

Provider methods follow Python's underscore convention:
- `method()` - exposed to templates
- `_method()` - internal only, not exposed

```python
class FileProvider(Provider):
    async def read(self, path: str) -> str:           # Exposed as colin.file.read()
    async def exists(self, path: str) -> bool:        # Exposed as colin.file.exists()
    async def get_last_updated(self, path: str):      # Exposed
    async def _write(self, path: str, content: str):  # Internal only
```

The template engine filters out underscore methods when exposing providers.

### 4. Utilities Outside the Namespace

The `colin` namespace is exclusively for providers. Utilities and other functions are registered as regular Jinja functions/filters outside the namespace:

```jinja
{# Providers under colin #}
{{ colin.file.read('/path') }}
{{ colin.llm.extract(content, 'prompt') }}

{# Utilities as regular functions #}
{{ env('API_KEY') }}
{{ now() }}
{{ ref('other-doc') }}
```

## Examples

### Complete Template

```markdown
---
name: Engineering Status
---

# Engineering Status

## GitHub Issues
{% set issues = colin.mcp.github.resource('repo://acme/platform/issues?state=open') %}
{{ issues.content }}

## S3 Data
{% set metrics = colin.s3.get('analytics/weekly-metrics.json') %}
{{ metrics | from_json | extract('key trends') }}

## Analysis
{% llm %}
Assess team velocity based on:

Issues: {{ issues.content }}
{% endllm %}
```

## Consequences

- `providers` namespace renamed to `colin`
- No more artificial elevation of `mcp`/`llm` to root
- Underscore convention distinguishes internal vs template-exposed methods
- Utilities remain outside the `colin` namespace as regular functions

## Migration

1. Rename internal `providers` namespace to `colin`
2. Update template engine to expose `colin.*` instead of `providers.*`
3. Remove root-level `mcp` and `llm` aliases
4. Update documentation and examples
