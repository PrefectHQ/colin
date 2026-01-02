# ADR 018: Storage Architecture

**Status**: Accepted
**Date**: 2025-01-02

## Context

Colin currently writes all compiled files to `target/` with the manifest at `target/manifest.json`. This conflates two concerns:

1. **Cache layer**: Compiled artifacts for incremental builds and LLM reproducibility
2. **Published outputs**: Files users actually want to consume

This creates several problems:

- No way to have "helper" files that support compilation but shouldn't appear in final output
- Unclear what `ref('file').path` should return when files are being compiled vs. consumed
- Manifest lives in the output directory, mixing build metadata with build artifacts
- LLM outputs need stable caching for reproducibility, but there's no clear contract about what gets committed

## Decision

### Two-layer storage architecture

```
project/
├── colin.toml
├── models/              # source files
├── .colin/              # cache layer (fixed location)
│   ├── manifest.json    # build metadata, timestamps
│   └── compiled/        # all compiled artifacts
└── target/              # published outputs only (configurable)
```

**`.colin/`**: Fixed location in project root (like `.git/`). Contains all compiled artifacts and the manifest. This is the source of truth for compiled content.

**`target/`**: Configurable via `target-path`. Contains only published files. This is what users consume.

### Visibility: publish vs internal

Files can be marked as internal (compile but don't publish):

**Frontmatter:**
```yaml
colin:
  publish: false
```

**Naming convention:** Files prefixed with `_` default to `publish: false`:
```
models/
├── greeting.md          # published (default)
├── _helpers.md          # internal (name convention)
└── data.md              # internal (frontmatter override)
```

### Ref resolution

`ref()` reads content from `.colin/compiled/` (source of truth). Path accessors resolve to `target/` for linking:

| Property | Published file | Internal file |
|----------|---------------|---------------|
| `.content` | `.colin/compiled/` | `.colin/compiled/` |
| `.path` | `target/file.md` | **Error** |
| `.relative_path` | `file.md` | **Error** |

Accessing `.path` on internal files raises an error—linking to unpublished files is a bug.

### Artifact storage model

```python
class CompiledArtifact:
    uri: str                # project://greeting.md
    content: str            # compiled content
    output_hash: str        # content hash for cache invalidation
    publish: bool           # if False, don't copy to target/
    metadata: dict          # frontmatter, format, etc.
```

**Content-addressed artifacts**: Only rewritten when content actually changes.

**Manifest timestamps**: Update every evaluation for staleness checks (`expires: 7d`).

### Storage abstraction

```python
class ArtifactStorage(Protocol):
    def get(self, uri: str) -> CompiledArtifact | None
    def put(self, artifact: CompiledArtifact) -> None
    def list(self) -> list[str]
```

Default: filesystem in `.colin/compiled/`. Plugins can implement remote storage (S3, database).

### Git behavior

**Default: commit `.colin/`**. LLM outputs need cache for reproducibility—without it, `llm.extract()` could return different content on rebuild, breaking downstream consumers. The cache is part of the reproducible build contract.

Artifacts are content-addressed (minimal churn). Manifest updates timestamps (single file, acceptable churn).

Storage plugins provide escape hatch for projects that want remote cache instead.

## Rationale

1. **Separation of concerns**: Cache is build machinery; target is user-facing output
2. **Internal files**: Natural support for helper/data files that shouldn't pollute output
3. **LLM reproducibility**: Committing cache ensures stable builds across machines
4. **Clear ref semantics**: `.content` always works; `.path` is for published linking
5. **Plugin-ready**: Storage abstraction enables future remote backends

## Consequences

- New `.colin/` directory in all projects
- Manifest moves from `target/manifest.json` to `.colin/manifest.json`
- Compiled artifacts write to `.colin/compiled/` first, then publish step copies to `target/`
- `ref().path` errors on internal files
- `_` prefix naming convention for internal files
- Projects should commit `.colin/` by default

## Alternatives Considered

1. **Gitignore `.colin/` by default**: Simpler, but loses LLM reproducibility
2. **Cache outside project (`~/.cache/colin/`)**: Cleaner separation, but loses portability
3. **`colin.internal: true` frontmatter**: Less intuitive than `publish: false`
4. **Naming convention only**: Magic, less explicit than frontmatter option
