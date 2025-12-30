"""Pydantic models for Colin manifest and documents."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


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

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    """When this call was made."""


class ColinConfig(BaseModel):
    """Colin-specific configuration from the colin: block in frontmatter."""

    output: str = "markdown"
    """Output format (e.g., 'markdown', 'skill')."""

    refresh: str | None = None
    """Refresh interval (future feature)."""

    storage: str | None = None
    """Storage backend (future feature)."""

    materialization: str | None = None
    """Materialization strategy (future feature)."""


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

    refs_evaluated: list[str] = Field(default_factory=list)
    """URIs of refs that were resolved during compilation."""

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

    def get_document(self, uri: str) -> DocumentMeta | None:
        """Get metadata for a document by URI."""
        return self.documents.get(uri)

    def set_document(self, uri: str, meta: DocumentMeta) -> None:
        """Set metadata for a document."""
        self.documents[uri] = meta

    def get_dependents(self, uri: str) -> list[str]:
        """Find all documents that depend on the given URI."""
        dependents = []
        for doc_uri, doc in self.documents.items():
            if uri in doc.refs_evaluated:
                dependents.append(doc_uri)
        return dependents

    def get_llm_call(self, doc_uri: str, call_id: str) -> LLMCall | None:
        """Get a cached LLM call for a document."""
        doc = self.get_document(doc_uri)
        if doc is None:
            return None
        return doc.llm_calls.get(call_id)


class RefResult(BaseModel):
    """Structured result from ref() calls.

    This is what ref('some/uri') returns. The __str__ method returns
    a placeholder to avoid accidentally dumping large content into templates.
    Use .content to get the actual content.
    """

    name: str
    """Document name (from frontmatter or derived from URI)."""

    description: str | None = None
    """Description from frontmatter."""

    content: str
    """The compiled output content."""

    template: str
    """The raw uncompiled template source."""

    updated: datetime
    """When the document was last compiled."""

    uri: str
    """The ref URI."""

    def __str__(self) -> str:
        """Return placeholder to avoid accidentally dumping large content."""
        return f"Ref({self.uri!r})"


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

    refs_evaluated: list[str] = Field(default_factory=list)
    """URIs of refs that were resolved."""

    llm_calls: dict[str, LLMCall] = Field(default_factory=dict)
    """LLM calls made during compilation."""

    total_cost_usd: float = 0.0
    """Total cost of LLM calls."""
