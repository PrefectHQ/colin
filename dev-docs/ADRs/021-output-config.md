# ADR 021: Output Configuration

**Status**: Accepted
**Date**: 2025-01-06
**Supersedes**: Parts of ADR 018 (visibility section)

## Context

The current output configuration is a single string: `output: json`. This controls only the format. Users cannot control where the artifact is written - the output path always mirrors the source path with the format's extension applied.

Use cases requiring more control:
- Writing `models/reports/summary.md` to `output/daily/summary.json`
- Custom filenames independent of source file names
- Future formats (like `skill`) that may have format-specific options

Additionally, ADR 018 placed `private: bool` at the `colin:` level. This creates conceptual overlap - `private` is fundamentally about output behavior, not document identity.

## Decision

Replace `output: str` with structured configuration:

```yaml
colin:
  output:
    format: json             # transformation (default: markdown)
    path: daily/report.json  # artifact location (default: source stem + extension)
    publish: true            # copy to output/ (default: true)
```

### Key changes

1. **`format`**: Replaces the old `output: string`. Controls transformation pipeline.

2. **`path`**: New. Relative to output dir. Supports subdirectories. Determines location in both `.colin/compiled/` and `output/`.

3. **`publish`**: Replaces `private: bool`. Inverted semantics (`publish: false` = was `private: true`). Moved inside `output:` block because it's an output concern.

4. **`_` prefix convention**: Still works, sets `publish: false` by default.

5. **Renderers receive config**: Full `OutputConfig` passed to renderers. Format-specific renderers can validate or use additional options.

### No shorthand

Always use the object form. No `output: json` string shorthand.

### Restructuring `is_private` → `is_published`

`is_private` is replaced with `is_published` (inverted semantics). `DocumentMeta` stores the resolved publish status (computed from `output.publish` + `_` prefix convention). This is used by:
- Emit step: decides whether to copy to output/
- `ProjectResource.path`: errors if `is_published=false`

All internal operations use `.compiled/` exclusively - they don't care about publish status except for these two cases.

### User-facing terminology

In documentation we refer to files with `publish: false` as "private documents" - this is clearer for users than "unpublished documents" which might imply the document is incomplete or unusable.

## Rationale

1. **Output config for output concerns**: Format, path, and publish are all about "what artifact is produced and where does it go." Grouping them is natural.

2. **`publish` over `private` in config**: Inside an `output:` block, "publish" describes the action. We still call them "private documents" in user-facing docs.

3. **Simplified internals**: Fewer places track publish state. The emit step and path accessor are the only consumers.

4. **Renderer extensibility**: Passing full config to renderers allows format-specific options without core changes.

## Consequences

- `colin.private` frontmatter key no longer exists (now `output.publish`)
- `is_private` renamed to `is_published` in `DocumentMeta` (inverted semantics)
- `is_private` removed from `CompiledDocument` (derived when needed)
- Compiled dir structure mirrors `output.path`, not source path
- No string shorthand - always use object form
- Documentation refers to "private documents" even though config says `publish`

## Alternatives Considered

1. **`filename` instead of `path`**: Rejected because subdirectories are supported
2. **Keep `private` at colin level**: Creates conceptual split between output config and visibility
3. **Infer format from path extension**: Rejected - ambiguous with formats like `skill` that produce JSON
4. **String shorthand (`output: json`)**: Rejected - explicit structure is clearer, and path is commonly needed
