"""Pydantic models for Colin manifest and documents."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, TypedDict

from pydantic import BaseModel, Field, StringConstraints

# Re-export duration utilities for backwards compatibility
from colin.utilities.temporal import (  # noqa: F401
    CalendarDuration,
    Duration,
    parse_duration,
)


class Address(TypedDict):
    """Structured address for re-fetching a resource.

    Stored in manifest to track dependencies. Contains just enough
    info to re-fetch the resource via provider.load_address(payload).

    The payload is provider-specific and should contain a 'type' field
    when the provider supports multiple addressable types.

    Examples:
        S3: {"provider": "s3", "instance": "", "payload": {"bucket": "b", "key": "k"}}
        MCP: {"provider": "mcp", "instance": "github", "payload": {"type": "resource", "uri": "colin://hello"}}
        HTTP: {"provider": "http", "instance": "", "payload": {"url": "https://..."}}
    """

    provider: str
    """Provider type (e.g., 's3', 'mcp', 'http')."""

    instance: str
    """Provider instance name (e.g., 'dev', 'github'). Empty string for default."""

    payload: dict[str, Any]
    """Provider-specific data for re-fetching. Should include 'type' for discrimination."""


class RefreshPolicy(str, Enum):
    """Refresh policy for document rebuilding."""

    ALWAYS = "always"
    """Always rebuild the document."""

    AUTO = "auto"
    """Rebuild only if stale (source changed, refs updated, or time expired)."""

    ONCE = "once"
    """Only build if no cached output exists."""


# Duration pattern: number + optional 'c' prefix + unit (m, h, d, w, M, Q)
# Examples: 30m, 1h, 7d, 2w, 1M, 1Q, 15cm, 1cd, 1cw, 3cM, 1cQ
StaleDuration = Annotated[str, StringConstraints(pattern=r"^\d+c?[mhdwMQ]$")]


class RefreshConfig(BaseModel):
    """Configuration for document refresh behavior."""

    policy: RefreshPolicy = RefreshPolicy.AUTO
    """Refresh policy (always, auto, once)."""

    stale: StaleDuration | None = None
    """Time-based staleness threshold (e.g., '1h', '1d', '1w')."""


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

    refresh: RefreshConfig = Field(default_factory=RefreshConfig)
    """Refresh configuration (policy and time-based staleness)."""

    storage: str | None = None
    """Storage backend (future feature)."""


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
    """Hash of the compiled output."""

    compiled_at: datetime | None = None
    """When this document was last compiled."""

    refs_evaluated: list[Address] = Field(default_factory=list)
    """Addresses of refs that were resolved during compilation."""

    llm_calls: dict[str, LLMCall] = Field(default_factory=dict)
    """LLM calls made during compilation, keyed by call_id."""

    total_cost_usd: float = 0.0
    """Total cost of all LLM calls for this document."""

    artifacts: list[ArtifactRef] = Field(default_factory=list)
    """Artifacts written for this document (concrete URIs)."""


class Manifest(BaseModel):
    """Root manifest structure, persisted as JSON."""

    version: str = "1"
    """Manifest format version."""

    compiled_at: datetime | None = None
    """When the last compilation completed."""

    documents: dict[str, DocumentMeta] = Field(default_factory=dict)
    """Document metadata, keyed by URI."""

    cache: dict[str, CacheEntry] = Field(default_factory=dict)
    """Global cache for provider function results."""

    def get_document(self, uri: str) -> DocumentMeta | None:
        """Get metadata for a document by URI."""
        return self.documents.get(uri)

    def set_document(self, uri: str, meta: DocumentMeta) -> None:
        """Set metadata for a document."""
        self.documents[uri] = meta

    def get_dependents(self, uri: str) -> list[str]:
        """Find all documents that depend on the given URI.

        For project:// URIs, matches against Address payloads with matching path.
        """
        # Extract path from project:// URI
        path = uri.split("://", 1)[1] if "://" in uri else uri

        dependents = []
        for doc_uri, doc in self.documents.items():
            for addr in doc.refs_evaluated:
                # Match project refs by path
                if addr["provider"] == "project" and addr["payload"].get("path") == path:
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
    """Hash of the compiled output."""

    refs_evaluated: list[Address] = Field(default_factory=list)
    """Addresses of refs that were resolved."""

    llm_calls: dict[str, LLMCall] = Field(default_factory=dict)
    """LLM calls made during compilation."""

    total_cost_usd: float = 0.0
    """Total cost of LLM calls."""
