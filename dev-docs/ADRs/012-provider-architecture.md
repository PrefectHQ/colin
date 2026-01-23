# ADR 012: Provider Architecture

**Status**: Accepted (staleness model superseded by [ADR 017](017-resource-and-ref-architecture.md))
**Date**: 2025-12-29
**Updated**: 2026-01-01

## Context

Colin's current architecture is tightly coupled to the filesystem. Models are discovered from directories, the manifest is a JSON file, and outputs are written to a target directory. This works well for local development but prevents Colin from supporting other backends like databases, object stores, or knowledge graphs.

We want Colin to support scenarios like:
- Models in git (filesystem), compiled outputs pushed to S3
- Templates that reference external data from MCP servers or APIs
- Custom template functions provided by domain-specific integrations

## Goals

1. Separate storage backends from the compilation engine
2. Allow templates to reference external data sources
3. Support providers with varying capabilities (read-only vs read-write)
4. Keep zero-config filesystem behavior as the default

## Key Insight: Provider = Low-Level I/O

A provider is fundamentally a low-level I/O handler. The base capability is fetching content; storage providers extend this with writing.

**Provider** - Fetches content, returns Resource objects. Examples: MCP servers, HTTP APIs, S3.

**Storage** - Provider that can also write. Used for project/artifact storage. Examples: filesystem, S3.

**ref()** - User-facing function that tracks dependencies. Accepts string paths (project refs) or Resource objects (provider refs).

**Renderer** - Separate from providers entirely. Pure content transformation (not URI-based). Lives in `renders/` alongside `providers/`.

This separation is critical:
- Provider template functions return `Resource` objects (content + ref + version)
- `ref()` tracks the resource's Ref for staleness checking
- This allows reading without dependency tracking when needed (skip `ref()` wrapper)

> **Note:** The staleness/tracking model has evolved. See [ADR 017](017-resource-and-ref-architecture.md) for the current Resource/Ref architecture.

The directory structure:
```
colin/
  providers/
    base.py              # Provider base class (read returns str)
    project.py           # ProjectProvider (wraps provider for project:// scheme)
    mcp.py               # MCPProvider - read-only
    storage/
      base.py            # Storage base class (extends Provider, adds write)
      file.py            # FileStorage - local filesystem
  renders/
    base.py              # Renderer base class with validate()
    json.py              # JSON validation
    yaml.py              # YAML validation
    markdown.py          # Markdown passthrough
```

## Decision

### Base Classes

Providers use abstract base classes (ABC):

```python
# providers/base.py
class Provider(ABC):
    """Low-level I/O for a URI scheme. Returns raw content."""
    scheme: str

    @abstractmethod
    async def read(self, path: str) -> str:
        """Read content from path.

        Path has scheme stripped (e.g., 'greeting.md' not 'project://greeting.md').
        """
        ...

# providers/storage/base.py
class Storage(Provider):
    """Provider that also supports writing. Used for artifacts."""

    @abstractmethod
    async def write(self, path: str, content: str) -> None:
        """Write content to relative path."""
        ...

# providers/project.py
class ProjectProvider(Provider):
    """Provider for project:// URIs. Wraps artifact storage."""
    scheme: str = "project"

    def __init__(self, provider: Provider) -> None:
        self._provider = provider

    async def read(self, path: str) -> str:
        return await self._provider.read(path)
```

Key design choices:
- `read()` returns `str`, not `RefResult` - the ref() function handles wrapping
- `write()` returns `None` - we know where we requested the write
- Method names are intentionally minimal: `read` and `write`
- Paths have scheme stripped - routing already happened

### Storage with Base Path

Storage implementations know their base location:

```python
class FileStorage(Storage):
    scheme: str = "file"

    def __init__(self, base_path: Path) -> None:
        self.base_path = base_path.resolve()

    async def read(self, path: str) -> str:
        full_path = self.base_path / path
        return full_path.read_text(encoding="utf-8")

    async def write(self, path: str, content: str) -> None:
        full_path = self.base_path / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
```

This means:
- Storage receives relative paths only
- Storage resolves to full paths internally
- No URI parsing in storage - that's already done

### ProjectConfig as Source of Truth

`colin.toml` is the source of truth. Config stores resolved absolute paths:

```python
class ProjectConfig(BaseModel):
    project_root: Path     # Where colin.toml lives
    model_path: Path       # Absolute path to models
    output_path: Path      # Absolute path to output
    manifest_path: Path    # Absolute path to manifest.json
```

Paths are resolved at load time by `load_project()`, stored as absolute paths. The engine and storage don't need to do path resolution.

### Engine Takes Config

The engine takes config and artifact storage, loads manifest internally:

```python
def __init__(
    self,
    config: ProjectConfig,
    artifact_storage: Storage,
    default_model: str,
) -> None:
    self.config = config
    self.artifact_storage = artifact_storage
    self.manifest = self._load_manifest()  # From config.manifest_path
    self._project_provider = ProjectProvider(artifact_storage)
```

This means:
- Engine doesn't take separate paths - config has everything
- Engine loads manifest from config.manifest_path
- Engine creates ProjectProvider internally

### The ref() Function

`ref()` in context.py handles:
1. Parsing URI to extract scheme and path
2. Routing to provider for scheme
3. Calling `provider.read(path)` → `str`
4. Creating `RefResult` from content
5. Tracking dependency

This separation allows:
- Providers to be simple I/O handlers
- Dependency tracking in one place
- Reading without tracking when needed

### Renderers with validate()

Renderers have a `validate()` method for format checking:

```python
class Renderer(ABC):
    name: str
    extension: str = ".md"

    @abstractmethod
    def render(self, document: CompiledDocument) -> RenderResult: ...

    def validate(self, content: str) -> None:
        """Override to validate output format. Raises if invalid."""
        pass

class JSONRenderer(Renderer):
    def validate(self, content: str) -> None:
        json.loads(content)  # Raises JSONDecodeError if invalid

    def render(self, document: CompiledDocument) -> RenderResult:
        self.validate(document.output)
        return RenderResult(...)
```

### MCP as a Provider

MCP servers are providers that return raw content from `read()`, plus template functions accessible via `colin.mcp.<name>`:

```python
class MCPProvider(Provider):
    scheme: str  # Set to "mcp" or "mcp.<instance>"

    async def read(self, path: str) -> str:
        """Parse path, fetch resource/prompt, return content."""
        ...

    def get_functions(self) -> dict[str, Callable[..., Awaitable[object]]]:
        return {
            "resource": self._template_resource,
            "prompt": self._template_prompt,
        }
```

## Rationale

**Why does read() return str, not RefResult?** Separation of concerns. Provider handles I/O. ref() handles dependency tracking and wrapping. This allows reading without tracking when needed.

**Why does write() return None?** We know where we requested the write. No need for confirmation.

**Why does Storage take base_path?** Storage works with relative paths. Base path is set at construction. No path resolution at write time.

**Why does Engine take config?** Config is the source of truth. Engine shouldn't assemble paths itself. This eliminates the previous problem of taking abstract Storage but concrete Path arguments.

**Why does Engine load manifest internally?** Manifest location is in config. Engine is responsible for its own state.

**Why is ProjectProvider in providers/project.py?** It's a Provider (not Storage) that wraps a Provider. It doesn't belong in the storage directory even though it's typically instantiated with Storage.

## Consequences

- Provider.read() returns str, not RefResult
- ref() creates RefResult and tracks dependencies
- Storage receives relative paths, knows its base
- Engine takes config, loads manifest internally
- ProjectProvider is a Provider wrapping a Provider (not Storage-specific)
- Renderers have validate() for format checking

## Implementation Status

Completed:
1. ✅ Provider base class with `read()` returning str
2. ✅ Storage base class extending Provider with `write()` returning None
3. ✅ FileStorage with base_path constructor
4. ✅ ProjectProvider wrapping a Provider
5. ✅ MCPProvider with read() returning str
6. ✅ Renderer base class with validate()
7. ✅ JSON and YAML renderers with validation
8. ✅ Engine taking config, loading manifest internally
9. ✅ ProjectConfig with resolved absolute paths

Future:
- S3Storage for object storage
- HTTPProvider for web APIs
