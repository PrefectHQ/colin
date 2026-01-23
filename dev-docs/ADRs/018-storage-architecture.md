# ADR 018: Storage Architecture

**Status**: Accepted
**Date**: 2025-01-02

## Context

Colin writes all compiled files to `output/` with the manifest at `.colin/manifest.json`. This separates two concerns:

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
└── output/              # published outputs only (configurable)
```

**`.colin/`**: Fixed location in project root (like `.git/`). Contains all compiled artifacts and the manifest. This is the source of truth for compiled content.

**`output/`**: Configurable via `output-path`. Contains only published files. This is what users consume. **This directory is fully managed by Colin**—it may be completely wiped and rebuilt on each compile. Users should not place hand-written files here; instead, copy files out of `output/` if needed elsewhere.

### Compilation pipeline

Compilation produces final artifacts in a single pass:

```
models/           →  .colin/compiled/  →  output/
(source files)       (final artifacts)    (literal copy)
     ↓                     ↓                    ↓
  COMPILE              STORE               PUBLISH
  (Jinja +            (write)             (copy public)
   render)
```

**Compilation = Jinja + rendering**: Template rendering (Jinja) and format rendering (JSON, YAML) happen together. The result is the final artifact—no further transformation.

**Compiled = final**: Files in `.colin/compiled/` are the finished artifacts. A JSON document is stored as valid JSON, not intermediate markdown.

**Publishing = copy**: The publish step simply copies public files from `.colin/compiled/` to `output/`. No transformation, no re-rendering.

**ref() by output name**: References are to OUTPUT documents by their actual filenames. `ref("config.json")` looks for `config.json` in compiled/. `ref("config")` defaults to `ref("config.md")`.

### Visibility: public vs private

Files can be marked as private (compile but don't copy to output).

**Naming convention (preferred):** Any path segment under the models root that starts with `_` marks the file as private. This is the idiomatic way to mark internal/helper files:

```
models/
├── greeting.md          # public (copied to output/)
├── _helpers.md          # private (stays in .colin/compiled/)
├── _data.md             # private
├── _partials/intro.md   # private (directory starts with _)
└── utils.md             # public
```

Only path segments under the models root count. Parent directories have no effect—if your project is at `~/Developer/_my_project/models/`, the `_my_project` prefix does not make files private.

**Frontmatter override:** For edge cases where renaming isn't practical:

```yaml
colin:
  private: true   # make a non-prefixed file private
```

Or to publish a `_`-prefixed file:

```yaml
colin:
  private: false  # override the _ convention
```

### Ref resolution

`ref()` reads content from `.colin/compiled/` (source of truth). Path accessors resolve to `output/` for linking:

| Property | Public file | Private file |
|----------|-------------|--------------|
| `.content` | `.colin/compiled/` | `.colin/compiled/` |
| `.path` | `output/file.md` | **Error** |
| `.relative_path` | `file.md` | **Error** |

Accessing `.path` on private files raises an error—linking to files that won't exist in `output/` is a bug.

### Artifact storage model

```python
class CompiledArtifact:
    uri: str                # project://greeting.md (source identity)
    output_path: str        # greeting.md or config.json (actual filename)
    content: str            # final rendered content (JSON, YAML, or markdown)
    output_hash: str        # content hash for cache invalidation
    is_private: bool        # if True, don't copy to output/
    metadata: dict          # frontmatter, format, etc.
```

**Content is final**: The `content` field contains the fully rendered artifact—valid JSON for JSON outputs, valid YAML for YAML outputs.

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
2. **Private files**: Natural support for helper/data files that shouldn't pollute output
3. **LLM reproducibility**: Committing cache ensures stable builds across machines
4. **Clear ref semantics**: `.content` always works; `.path` is for published linking
5. **Plugin-ready**: Storage abstraction enables future remote backends
6. **Discoverable convention**: `_` prefix is visible in filesystem and familiar from Sass/Python

## Consequences

- New `.colin/` directory in all projects
- Manifest is at `.colin/manifest.json`
- Compilation produces final artifacts (Jinja + rendering in one step)
- `.colin/compiled/` contains ready-to-use files (JSON is valid JSON, etc.)
- Publishing is a simple copy from `.colin/compiled/` to `output/`
- `ref("file.json")` looks for the actual output filename
- `ref("file")` defaults to `ref("file.md")`
- `ref().path` errors on private files
- `_` prefix naming convention marks files as private (idiomatic)
- `colin.private: bool` frontmatter available as override
- Projects should commit `.colin/` by default

## Alternatives Considered

1. **Gitignore `.colin/` by default**: Simpler, but loses LLM reproducibility
2. **Cache outside project (`~/.cache/colin/`)**: Cleaner separation, but loses portability
3. **`colin.publish: false` frontmatter**: "Private" is clearer and more common terminology
4. **Naming convention only (no frontmatter)**: Simpler but less flexible for edge cases
5. **Frontmatter only (no naming convention)**: Less discoverable, hidden in file metadata
