# ADR 002: Frontmatter Namespacing

**Status**: Accepted
**Date**: 2024-12-27

## Context

Colin documents are Jinja-templated markdown with YAML frontmatter. However, the output formats (like Skills) may also use frontmatter for their own purposes. For example, a Skill might have:

```yaml
---
name: project-status
description: Provides project status
allowed-tools:
  - Read
  - Bash
---
```

If Colin's configuration (like `output: skill`) is in the same frontmatter, there's collision risk and confusion about what's Colin config vs. document metadata.

## Decision

Colin config is namespaced under a `colin:` key in frontmatter. Everything outside this key is document metadata that passes through to the output.

```yaml
---
colin:
  output: skill          # Colin config
  refresh: 1h            # Colin config (future)

# Document metadata (passed through to output)
name: project-status
description: Provides project status
allowed-tools:
  - Read
  - Bash
---
```

## Rationale

1. **Clear separation**: Colin config is clearly distinguished from document metadata
2. **No collision**: Document authors can use any frontmatter keys without worrying about Colin reserved words
3. **Forward compatible**: New Colin config options don't risk breaking existing documents
4. **Intuitive**: The `colin:` prefix makes it obvious what's being configured

## Alternatives Considered

1. **Separate config file per document**: More files, harder to keep in sync
2. **Special prefix for document metadata**: Inverts the burden to document authors
3. **Flat structure with reserved keys**: Risk of collision as features grow

## Consequences

- Colin must parse frontmatter, extract `colin:` block, and pass rest as metadata
- Document authors must nest Colin config under `colin:` key
- Simpler mental model: "colin: is for Colin, rest is for the document"
