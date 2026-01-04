"""Pydantic models for Colin manifest and documents."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

import pydantic_core
from pydantic import BaseModel, Field, StringConstraints, field_validator

# Re-export duration utilities for backwards compatibility
from colin.utilities.temporal import (  # noqa: F401
    CalendarDuration,
    Duration,
    parse_duration,
)


class Ref(BaseModel):
    """A reference to an external dependency.

    In Colin's compilation model, documents can depend on external resources
    (S3 objects, files, MCP resources, other compiled documents). To track
    these dependencies for staleness detection, we need more than just "this
    document depends on X" - we need a way to check whether X has changed.

    A Ref solves this by storing replay instructions: everything needed to
    re-fetch or query the resource. When checking staleness, Colin replays
    each Ref to get the current version and compares it to the version
    stored at compile time.

    Attributes:
        provider: Provider type (e.g., 's3', 'mcp', 'http', 'project').
        connection: Provider instance name (e.g., 'prod' for s3.prod). Empty for default.
        method: The provider method to call (e.g., 'get', 'resource').
        args: Arguments to pass to the method (must be JSON-serializable).

    Examples:
        S3: Ref(provider="s3", connection="prod", method="get", args={"path": "bucket/key"})
        MCP: Ref(provider="mcp", connection="github", method="resource", args={"uri": "..."})
        Project: Ref(provider="project", connection="", method="get", args={"path": "greeting.md"})
    """

    provider: str
    """Provider type (e.g., 's3', 'mcp', 'http', 'project')."""

    connection: str
    """Provider instance name (e.g., 'prod' for s3.prod). Empty string for default."""

    method: str
    """The provider method to call."""

    args: dict[str, Any]
    """Arguments to pass to the method (must be JSON-serializable)."""

    def key(self) -> str:
        """Canonical key for manifest lookup.

        Returns a deterministic JSON string for use as a dict key.
        Uses pydantic_core.to_jsonable_python() to handle complex types
        (datetime, Pydantic models, etc.) in args.
        """
        return json.dumps(
            {
                "provider": self.provider,
                "connection": self.connection,
                "method": self.method,
                "args": pydantic_core.to_jsonable_python(self.args),
            },
            sort_keys=True,
        )


# Cache policy: controls when documents rebuild
# - "auto": rebuild when refs change or time expires (default)
# - "always": aggressive caching, only --no-cache rebuilds
# - "never": no caching, always rebuild
CachePolicy = Literal["auto", "always", "never"]

# Duration pattern: number + optional 'c' prefix + unit (m, h, d, w, M, Q)
# Examples: 30m, 1h, 7d, 2w, 1M, 1Q, 15cm, 1cd, 1cw, 3cM, 1cQ
ExpiresDuration = Annotated[str, StringConstraints(pattern=r"^\d+c?[mhdwMQ]$")]


class CacheConfig(BaseModel):
    """Configuration for document caching behavior."""

    policy: CachePolicy = "auto"
    """Cache policy (always, auto, never)."""

    expires: ExpiresDuration | None = None
    """Time-based expiration threshold (e.g., '1h', '1d', '7d')."""


class LLMCall(BaseModel):
    """Record of a single LLM invocation."""

    call_id: str
    """Identifier for this call (auto-generated or manual)."""

    input_hash: str
    """Hash of the input content."""

    output_hash: str
    """Hash of the output content."""

    output: str
    """The actual LLM response."""

    model: str
    """Model used (e.g., 'stub', 'haiku', 'sonnet')."""

    cost_usd: float = 0.0
    """Cost of this call in USD."""

    is_successful: bool = True
    """Whether the LLM call succeeded."""

    error: str | None = None
    """Error message if call failed."""

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    """When this call was made."""


class CacheEntry(BaseModel):
    """A cached provider function result."""

    cache_key: str
    """Unique key for this cache entry."""

    output: str
    """The cached result (JSON-serialized)."""

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    """When this entry was created."""


class ColinConfig(BaseModel):
    """Colin-specific configuration from the colin: block in frontmatter."""

    output: str = "markdown"
    """Output format (e.g., 'markdown', 'skill')."""

    cache: CacheConfig = Field(default_factory=CacheConfig)
    """Cache configuration (policy and expiration). Accepts shorthand: 'auto', 'always', 'never'."""

    storage: str | None = None
    """Storage backend (future feature)."""

    private: bool | None = None
    """Override private detection. None uses naming convention (_ prefix)."""

    @field_validator("cache", mode="before")
    @classmethod
    def _normalize_cache(cls, v: Any) -> CacheConfig | dict[str, Any]:
        """Accept shorthand 'cache: auto' as 'cache: {policy: auto}'."""
        if isinstance(v, str):
            return {"policy": v}
        return v


class Frontmatter(BaseModel):
    """Parsed frontmatter from a .colin file."""

    colin: ColinConfig = Field(default_factory=ColinConfig)
    """Colin-specific configuration."""

    metadata: dict[str, Any] = Field(default_factory=dict)
    """Document metadata (everything outside the colin: block)."""


class ArtifactRef(BaseModel):
    """Reference to a written artifact, stored in manifest."""

    uri: str
    """Concrete URI where artifact was written (e.g., 's3://bucket/greeting.json')."""

    format: str
    """Format used (e.g., 'json', 'markdown')."""

    hash: str
    """Content hash for staleness detection."""


class DocumentMeta(BaseModel):
    """Metadata for a compiled document, stored in manifest."""

    uri: str
    """Document URI (e.g., 'project://greeting.md')."""

    source_path: str | None = None
    """Absolute path to the source file (deprecated, use uri)."""

    source_hash: str
    """Hash of the source file content."""

    output_hash: str | None = None
    """Hash of the rendered output (used for versioning and content-addressed writes)."""

    output_path: str | None = None
    """Relative output filename after rendering (e.g., 'greeting.md' or 'greeting.json')."""

    is_private: bool = False
    """Whether this document is private (not published to output/)."""

    compiled_at: datetime | None = None
    """When this document was last compiled."""

    refs: list[Ref] = Field(default_factory=list)
    """Refs that were tracked during compilation."""

    ref_versions: dict[str, str] = Field(default_factory=dict)
    """Version of each ref at compile time (ref.key() -> version)."""

    llm_calls: dict[str, LLMCall] = Field(default_factory=dict)
    """LLM calls made during compilation, keyed by call_id."""

    total_cost_usd: float = 0.0
    """Total cost of all LLM calls for this document."""

    artifacts: list[ArtifactRef] = Field(default_factory=list)
    """Artifacts written for this document (concrete URIs)."""

    sections: dict[str, str] = Field(default_factory=dict)
    """Named sections extracted from the document (section_name -> raw_content)."""


class Manifest(BaseModel):
    """Root manifest structure, persisted as JSON."""

    model_config = {"extra": "ignore"}

    version: str = "1"
    """Manifest format version."""

    compiled_at: datetime | None = None
    """When the last compilation completed."""

    documents: dict[str, DocumentMeta] = Field(default_factory=dict)
    """Document metadata, keyed by URI."""

    cache: dict[str, CacheEntry] = Field(default_factory=dict)
    """Global cache for provider function results."""

    # Cached reverse index: output_path -> uri (not persisted)
    _output_path_index: dict[str, str] | None = None

    def _build_output_path_index(self) -> dict[str, str]:
        """Build index mapping output_path -> document uri."""
        return {
            doc.output_path: uri
            for uri, doc in self.documents.items()
            if doc.output_path is not None
        }

    def get_document(self, uri: str) -> DocumentMeta | None:
        """Get metadata for a document by URI."""
        return self.documents.get(uri)

    def get_document_by_output_path(self, output_path: str) -> DocumentMeta | None:
        """Find document by its output filename. O(1) after first call."""
        if self._output_path_index is None:
            self._output_path_index = self._build_output_path_index()
        uri = self._output_path_index.get(output_path)
        return self.documents.get(uri) if uri else None

    def set_document(self, uri: str, meta: DocumentMeta) -> None:
        """Set metadata for a document."""
        self.documents[uri] = meta
        # Invalidate cached index
        self._output_path_index = None

    def get_dependents(self, uri: str) -> list[str]:
        """Find all documents that depend on the given URI.

        For project:// URIs, matches against Refs with matching path.
        """
        # Extract path from project:// URI
        path = uri.split("://", 1)[1] if "://" in uri else uri

        dependents = []
        for doc_uri, doc in self.documents.items():
            for ref in doc.refs:
                # Match project refs by path
                if ref.provider == "project" and ref.args.get("path") == path:
                    dependents.append(doc_uri)
                    break
        return dependents

    def get_llm_call(self, doc_uri: str, call_id: str) -> LLMCall | None:
        """Get a cached LLM call for a document."""
        doc = self.get_document(doc_uri)
        if doc is None:
            return None
        return doc.llm_calls.get(call_id)


class ColinDocument(BaseModel):
    """A loaded .colin document before compilation."""

    uri: str
    """Document URI."""

    frontmatter: Frontmatter
    """Parsed frontmatter."""

    template_content: str
    """Template content (after frontmatter)."""

    source_hash: str
    """Hash of the source file."""


class CompiledDocument(BaseModel):
    """Result of compiling a document."""

    uri: str
    """Document URI."""

    frontmatter: Frontmatter
    """Parsed frontmatter."""

    output: str
    """Compiled output content."""

    source_hash: str
    """Hash of the source file."""

    output_hash: str
    """Hash of the rendered output (used for versioning and content-addressed writes)."""

    output_path: str
    """Output filename (e.g., 'greeting.md' or 'config.json'). Set during compilation."""

    is_private: bool = False
    """Whether this document is private (not published to output/)."""

    refs: list[Ref] = Field(default_factory=list)
    """Refs that were tracked during compilation."""

    ref_versions: dict[str, str] = Field(default_factory=dict)
    """Version of each ref at compile time (ref.key() -> version)."""

    llm_calls: dict[str, LLMCall] = Field(default_factory=dict)
    """LLM calls made during compilation."""

    total_cost_usd: float = 0.0
    """Total cost of LLM calls."""

    sections: dict[str, str] = Field(default_factory=dict)
    """Named sections extracted from the document (section_name -> raw_content)."""
