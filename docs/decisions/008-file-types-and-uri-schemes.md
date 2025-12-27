# ADR 008: Universal File Types and URI Schemes

**Status**: Accepted
**Date**: 2024-12-27

## Context

Colin initially used `.colin` as a custom extension for model files. This created friction:
- No IDE support (syntax highlighting, preview, linting)
- Double-clicking files doesn't "just work"
- dbt proved that using native extensions (`.sql`) with Jinja templating works well

Additionally, refs need to support multiple sources beyond local files: MCP resources, GitHub files, HTTP endpoints, etc.

## Decision

### Any File Type is a Model

Files in the `models/` directory (or configured `model-path`) are models regardless of extension:

```
models/
  report.md        → target/compiled/report.md
  config.json      → target/compiled/config.json
  schema.yaml      → target/compiled/schema.yaml
  query.sql        → target/compiled/query.sql
```

All files are processed with Jinja templating. The extension determines output format. IDEs treat them as their native type.

### Frontmatter for Configuration

Markdown and YAML files support frontmatter natively. For file types where frontmatter is awkward (JSON, SQL), configuration can come from:
1. A central `schema.yml` file (future, dbt-style)
2. Sidecar files (future)
3. Defaults

### URI Schemes for Refs

Refs use URI schemes to route to the appropriate input plugin:

```python
ref('file://reports/quarterly')      # Local model
ref('github://org/repo/docs/api.md') # GitHub file
ref('mcp://linear/issue/ABC-123')    # MCP resource
ref('https://api.example.com/data')  # HTTP endpoint
```

The scheme maps to an `InputPlugin.scheme` for resolution.

### Default Scheme

For convenience, schemaless URIs default to `file://`:

```python
ref('reports/quarterly')  # Equivalent to ref('file://reports/quarterly')
```

Local model refs can omit the scheme since they're always local files.

### Custom URIs via Frontmatter

A file can declare a custom URI to decouple reference name from file path:

```yaml
---
colin:
  uri: reports/quarterly
---
```

A file at `models/drafts/q4-report.md` could be referenced as `ref('reports/quarterly')`.

## Rationale

1. **IDE support**: Native extensions get syntax highlighting, preview, linting
2. **dbt precedent**: Proven pattern - SQL files with `{{ }}` work fine in SQL editors
3. **Extensibility**: URI schemes enable MCP, GitHub, HTTP sources via plugins
4. **Simplicity**: Schemaless refs for the common case (local models)
5. **Flexibility**: Frontmatter URI override decouples organization from API

## Consequences

- Discovery changes from `*.colin` to all files in `models/`
- Need to handle frontmatter parsing per file type (or skip for non-frontmatter types)
- URI parsing needed to extract scheme and route to plugins
- Default scheme provides backwards-compatible simple refs
