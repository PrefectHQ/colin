# ADR 016: Addressable and Structured Addresses

> **Superseded by [ADR 017](017-resource-and-ref-architecture.md)**

**Status**: Superseded
**Date**: 2026-01-01

## Context

Colin's provider architecture (ADR 012) established providers as low-level I/O handlers. The original design used URIs as the primary addressing mechanism for `ref()`.

However, URIs become awkward for complex resources:
- SQL queries: `sql://SELECT * FROM users WHERE...` requires heavy encoding
- MCP tool calls with arguments: `mcp.github://?tool=search&query=...&filters=...`
- Any resource requiring structured parameters

The core problem: **URIs are great for human-readable addresses but painful for structured data.**

## Goals

1. Enable providers to return structured addresses that can be re-fetched without URI parsing
2. Let users call provider functions directly in templates
3. Give users control over what gets tracked as a dependency
4. Support staleness checking without loading full content

## Decision

### ref() Only Accepts Strings for File/Project Paths

`ref()` with a string argument is reserved for file and project paths:

```jinja
{{ ref("other-doc") }}        {# Project ref (relative path) #}
{{ ref("/etc/config") }}      {# File ref (absolute path) #}
```

For all other providers, use the provider's functions directly:

```jinja
{{ s3.get("bucket/key") }}                    {# Just reads, NOT tracked #}
{{ ref(s3.get("bucket/key")) }}               {# Reads AND tracked as dependency #}
{{ ref(colin.mcp.github.resource("colin://...")) }} {# MCP resource, tracked #}
```

### ref() Handles Coroutines

Since provider functions are async, they return coroutines. Jinja2's async mode awaits the outermost expression, but `ref(s3.get(...))` means `ref()` receives an unawaited coroutine.

Solution: `ref()` detects and awaits coroutines internally:

```python
async def ref(target: str | Addressable) -> Addressable:
    # Handle coroutines from provider calls
    if asyncio.iscoroutine(target):
        target = await target

    # Handle strings as file/project paths
    if isinstance(target, str):
        if os.path.isabs(target):
            return await file_provider.load(target)
        return await project_provider.load(target)

    # Addressable - track and return
    self._track_address(target.address())
    return target
```

### No Scheme Registration

Providers no longer need to register URI schemes. The `schemes` field is removed from Provider. Routing is simplified:
- Strings → file or project provider (based on absolute/relative path)
- Addressables → tracked directly via `address()`

### Address: A Structured Dict

An `Address` is a TypedDict with three fields:

```python
class Address(TypedDict):
    provider: str      # Provider namespace (e.g., "s3", "mcp", "http")
    instance: str      # Provider instance name (e.g., "dev", "github") or ""
    payload: dict[str, Any]  # Provider-specific data for re-fetching
```

The payload is provider-specific:

```python
# S3
{"bucket": "my-bucket", "key": "path/to/file.csv"}

# MCP resource
{"type": "resource", "uri": "colin://issues/ABC-123"}

# HTTP
{"url": "https://example.com/data.json"}
```

### Addressable: Base Class for Domain Objects

`Addressable` is an abstract base class that domain objects inherit from:

```python
class Addressable(ABC):
    @property
    @abstractmethod
    def content(self) -> str:
        """The content of this resource."""
        ...

    @property
    @abstractmethod
    def last_updated(self) -> datetime:
        """When this resource was last modified."""
        ...

    @abstractmethod
    def address(self) -> Address:
        """Return structured address for re-fetching."""
        ...

    def __str__(self) -> str:
        """Return content for template use."""
        return self.content
```

### Provider Methods

Providers implement `load_address()` for re-fetching from manifest:

```python
class Provider(ABC):
    @abstractmethod
    async def load_address(self, payload: dict[str, Any]) -> Addressable:
        """Load from structured payload. Required for staleness checking."""
        ...

    async def get_last_updated(self, payload: dict[str, Any]) -> datetime | None:
        """Get last modified time. Default loads full resource."""
        result = await self.load_address(payload)
        return result.last_updated
```

Providers expose their functionality via template functions (e.g., `s3.get()`, `mcp.resource()`), not URI-based access.

## Rationale

**Why no URI-based ref()?** URIs require encoding complex structured data. Provider functions are more natural and avoid encoding gymnastics.

**Why does ref() await coroutines?** Jinja2 awaits the outermost expression, but `ref(provider_call())` means ref receives an unawaited coroutine. Detecting and awaiting internally makes the API clean.

**Why separate file/project from other providers?** File and project refs are the common case in templates. Short syntax (`ref("doc")`) is ergonomic. Other providers have richer APIs via their functions.

**Why user-controlled dependency tracking?** Not every provider call should be a dependency. `{{ s3.get(...) }}` might be auxiliary data. Only `{{ ref(s3.get(...)) }}` creates a dependency edge.

**Why a base class instead of Protocol?** Provides shared `__str__()` implementation. All domain objects benefit from consistent template behavior.

## Consequences

- Providers don't register schemes
- Provider functions are called directly in templates
- `ref()` wrapping explicitly marks dependencies
- `load_address()` is required for staleness checking from manifest
- Complex resources don't need URI encoding

## Examples

### Template Usage

```jinja
{# Read S3 file, not tracked as dependency #}
{% set data = s3.get("bucket/config.json") %}

{# Read S3 file, tracked as dependency #}
{% set data = ref(s3.get("bucket/config.json")) %}

{# Project refs use string shorthand #}
{% set other = ref("other-doc") %}

{# HTTP resource #}
{% set api = ref(colin.http.get("api.example.com/data")) %}

{# MCP resource #}
{% set issue = ref(colin.mcp.github.resource("colin://issues/123")) %}
```

### S3Resource

```python
@dataclass
class S3Resource(Addressable):
    bucket: str
    key: str
    _content: str
    _last_updated: datetime | None = None
    _instance: str = ""

    @property
    def content(self) -> str:
        return self._content

    @property
    def last_updated(self) -> datetime:
        return self._last_updated or datetime.now(timezone.utc)

    def address(self) -> Address:
        return Address(
            provider="s3",
            instance=self._instance,
            payload={"bucket": self.bucket, "key": self.key},
        )
```

### S3Provider

```python
class S3Provider(Provider):
    async def load_address(self, payload: dict[str, Any]) -> S3Resource:
        """Re-fetch from manifest address."""
        return await self._fetch(payload["bucket"], payload["key"])

    async def get(self, path: str) -> S3Resource:
        """Template function: s3.get("bucket/key")"""
        bucket, key = path.split("/", 1)
        return await self._fetch(bucket, key)
```
