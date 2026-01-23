# ADR 011: Multi-File Output

**Status**: Partially Implemented
**Date**: 2024-12-29
**Updated**: 2026-01-10

## Implementation Status

- **`{% file %}` directive**: Implemented. Supports `path`, `format`, and `publish` arguments. See architecture.md for usage details.
- **Static file mappings**: Not yet implemented.
- **Output plugin-generated files**: Not yet implemented.

## Context

Colin's current model is 1:1—one template produces one output file. However, several use cases require generating multiple outputs from a single template or copying static files:

- A template that generates multiple related files (e.g., a skill plus supporting scripts)
- Static assets that need to be copied to the target directory
- Output plugins that generate supporting files (e.g., `__init__.py` alongside Python modules)

## Decision

Multi-file output is supported through three mechanisms:

### 1. `{% file %}` Directive

A Jinja block directive that creates additional output files:

```jinja
{% file "path/relative/to/output.json" %}
{
  "name": "{{ name }}",
  "generated": true
}
{% endfile %}
```

File blocks can contain any Jinja directives, including MCP resources:

```jinja
{% file "tools/analyzer.py" %}
{{ colin.mcp.scripts.resource('scripts://analyzer') }}
{% endfile %}
```

### 2. Static File Mappings in `colin.toml`

For known static assets, define mappings in project configuration:

```toml
[[static]]
src = "resources/utils.py"
dest = "lib/utils.py"

[[static]]
src = "resources/utils.py"    # Same source
dest = "backup/utils.py"      # Different destination

[[static]]
src = "resources/templates/"  # Directory
dest = "templates/"
```

Array-of-tables syntax (`[[static]]`) allows one source to be copied to multiple destinations.

### 3. Output Plugin-Generated Files

Output plugins can emit additional files beyond the primary document:

- A `skill` plugin could generate `__init__.py` alongside skill files
- A `python` plugin could generate type stubs
- A plugin could copy required assets referenced in the document

This is already supported by `OutputPlugin.emit() -> list[Path]`.

## Architecture Changes

**CompiledDocument model**:
```python
class CompiledDocument(BaseModel):
    uri: str
    output: str                           # Primary output (existing)
    additional_outputs: dict[str, str]    # path → content from {% file %} blocks
```

**Compilation flow**:
1. Static files copied first (from `[[static]]` config)
2. Templates compiled, `{% file %}` blocks captured in `additional_outputs`
3. Output plugins receive `CompiledDocument`, write primary + additional outputs
4. Output plugins may generate their own additional files

## Rationale

1. **`{% file %}` for dynamic content**: Templates can generate multiple related files with full Jinja power
2. **`[[static]]` for known assets**: Configuration-driven, no template needed for static files
3. **Output plugins for format-specific**: Plugins know what supporting files their format needs
4. **Composable**: These mechanisms work together—a skill template can use `{% file %}` while the skill plugin adds `__init__.py`

## Alternatives Considered

1. **`{% copy %}` directive**: Inline copying in templates
   - Problem: Static file mappings don't need template execution; config is cleaner
2. **`{source: dest}` in config**: Simple key-value mapping
   - Problem: One source can't map to multiple destinations
3. **Separate manifest file**: List of all outputs per template
   - Problem: Duplicates information, harder to maintain

## Consequences

- `CompiledDocument` gains `additional_outputs` field
- New `{% file %}` Jinja extension needed
- Static file copying added to compilation pipeline
- Output plugins already support multi-file via `list[Path]` return
- Primary output remains at URI-derived path; additional outputs at specified paths
