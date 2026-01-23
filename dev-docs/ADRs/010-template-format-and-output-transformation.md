# ADR 010: Template Format and Output Transformation

**Status**: Accepted
**Date**: 2024-12-29

## Context

Colin compiles templates into context documents. A key question is whether templates should match their output format (e.g., a JSON template for JSON output) or use a consistent source format with output plugins handling transformation.

Templates already contain Jinja directives (`{% llm %}`, `{{ ref() }}`), so they're not syntactically valid in their target format anyway. Additionally, ADR 002 established that Colin config lives in YAML frontmatter under a `colin:` key—but not all formats support frontmatter (JSON, Python, etc.).

## Decision

Colin templates are **always markdown documents** with YAML frontmatter. Output plugins transform compiled markdown into target formats (JSON, YAML, Python, etc.).

```
Template (.md with front matter) → Compile → Output Plugin transforms → Target format
```

The `colin:` namespace (ADR 002) separates Colin config from document metadata. When a document needs its own frontmatter (e.g., a skill file), the output plugin:

1. Strips the `colin:` block
2. Preserves remaining frontmatter (name, description, etc.)
3. Applies format-specific transformation (extension, validation)

Example skill template:
```yaml
---
colin:
  output: skill

name: my-skill
description: Analyzes sales data
allowed-tools:
  - Read
---

Skill content here...
```

## Output Plugin Responsibilities

| Plugin | Extension | Transforms |
|--------|-----------|------------|
| markdown | `.md` | None (pass-through) |
| skill | `.md` | Strip `colin:`, preserve rest |
| json | `.json` | Strip all frontmatter, validate JSON |
| yaml | `.yaml` | Strip `colin:`, preserve rest as YAML |
| python | `.py` | Strip frontmatter, optional linting |

## Rationale

1. **Consistent source format**: All templates use markdown with YAML frontmatter, regardless of output
2. **Standard tooling**: Markdown and YAML frontmatter are well-supported by editors, linters, etc.
3. **Natural for context**: Context documents are prose-heavy—markdown is the right fit
4. **Clean separation of concerns**: Templates focus on content; plugins handle format-specific transformation

## Alternatives Considered

1. **Templates match output format**: JSON templates for JSON output, etc.
   - Problem: Frontmatter doesn't work in JSON; templates aren't valid JSON anyway due to Jinja
2. **Multiple source formats**: Support .json.colin, .yaml.colin, etc.
   - Problem: Fragments the ecosystem, complicates tooling
3. **Frontmatter in comments**: `// colin: output: json` at top of JSON files
   - Problem: Format-specific parsing, not standard

## Consequences

- All templates are `.md` files with YAML frontmatter
- Output plugins must handle frontmatter stripping and format transformation
- Format-specific validation (JSON syntax, Python linting) happens in output plugins
- Structured output modes for LLM calls (e.g., JSON mode) are orthogonal—handled via LLM call parameters if needed
