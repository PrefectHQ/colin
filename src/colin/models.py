"""Pydantic models for Colin manifest and documents."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
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


class OutputConfig(BaseModel):
    """Configuration for document output behavior.

    Controls how a document is transformed and where its artifact is written.

    Attributes:
        format: Output format name (e.g., 'markdown', 'json', 'yaml', 'skill').
            Determines the renderer used to transform content.
        path: Relative path for the output artifact (e.g., 'reports/summary.json').
            Supports subdirectories. If None, uses source filename with format's extension.
        publish: Whether to copy the artifact to output/ directory.
            False means the file stays in .colin/compiled/ only (private document).
            Default is None, which uses the _ prefix naming convention.
    """

    format: str = "markdown"
    """Output format (e.g., 'markdown', 'json', 'yaml')."""

    path: str | None = None
    """Relative output path. None uses source filename with format's extension."""

    publish: bool | None = None
    """Copy to output/? None uses _ prefix convention (default: True if no _ prefix)."""

    @field_validator("path")
    @classmethod
    def _validate_path(cls, v: str | None) -> str | None:
        """Validate path is relative and doesn't escape output directory."""
        if v is None:
            return v

        p = Path(v)

        # Reject absolute paths
        if p.is_absolute():
            raise ValueError(f"output.path must be relative, got absolute path: {v}")

        # Reject paths that escape via ..
        if ".." in p.parts:
            raise ValueError(f"output.path cannot contain '..': {v}")

        return v

    def should_publish(self, uri: str) -> bool:
        """Determine if document should be published to output/.

        Resolution order:
        1. Explicit publish value if set
        2. Naming convention: any path segment starting with _ means private

        Args:
            uri: Document URI (e.g., 'project://path/to/file.md').
                The path part must be relative to models directory.

        Returns:
            True if document should be published to output/.
        """
        # Explicit value takes precedence
        if self.publish is not None:
            return self.publish

        # Naming convention: any _ segment marks as private (not published)
        path_part = uri.split("://", 1)[1] if "://" in uri else uri
        relative = Path(path_part)
        return not any(part.startswith("_") for part in relative.parts)


class LLMCall(BaseModel):
    """Record of a single LLM invocation."""

    call_id: str
    """Identifier for this call (unique per invocation, includes input hash)."""

    position_id: str | None = None
    """Position-based ID for previous_output lookup (e.g., 'llm_1_5' or 'llm_1_5:0' for loops)."""

    config_hash: str | None = None
    """Hash of provider config at call time. Used to validate previous_output lookup."""

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

    template: bool = True
    """Whether to process this file as a Jinja template.

    Set to false to skip template rendering entirely. The file content
    (minus frontmatter) passes through unchanged. Useful for documentation
    files that contain Jinja syntax as examples.
    """

    output: OutputConfig = Field(default_factory=OutputConfig)
    """Output configuration (format, path, publish)."""

    cache: CacheConfig = Field(default_factory=CacheConfig)
    """Cache configuration (policy and expiration). Accepts shorthand: 'auto', 'always', 'never'."""

    storage: str | None = None
    """Storage backend (future feature)."""

    depends_on: list[str] = Field(default_factory=list)
    """Explicit dependency hints for compilation ordering.

    Use this when you have dynamic refs that can't be statically detected,
    or when referencing outputs from {% file %} blocks.

    Example:
        colin:
          depends_on:
            - generator.md
            - other-dep.md
    """

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


class FileOutputMeta(BaseModel):
    """Metadata for a file created via {% file %} block.

    Stored in manifest for validity tracking and publish decisions.
    Content is stored on disk, not in manifest.
    """

    publish: bool | None = None
    """Whether to publish to output/. None = inherit from source document."""

    format: str = "markdown"
    """Renderer used (json, yaml, markdown)."""

    sections: dict[str, str] = Field(default_factory=dict)
    """Named sections extracted from this file (scoped to file, not parent)."""

    output_hash: str | None = None
    """Content hash for staleness detection of refs to this file output."""


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

    is_published: bool = True
    """Whether this document is published to output/. False = private document."""

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

    file_outputs: dict[str, FileOutputMeta] = Field(default_factory=dict)
    """Files created via {% file %} blocks (path -> metadata). Content stored on disk."""

    config_hash: str | None = None
    """Hash of colin.toml when this document was compiled."""


class Manifest(BaseModel):
    """Root manifest structure, persisted as JSON."""

    model_config = {"extra": "ignore"}

    version: str = "1"
    """Manifest format version."""

    project_name: str | None = None
    """Project name from colin.toml."""

    config_hash: str | None = None
    """Hash of colin.toml at last compilation."""

    compiled_at: datetime | None = None
    """When the last compilation completed."""

    documents: dict[str, DocumentMeta] = Field(default_factory=dict)
    """Document metadata, keyed by URI."""

    cache: dict[str, CacheEntry] = Field(default_factory=dict)
    """Global cache for provider function results."""

    # Cached reverse index: output_path -> uri (not persisted)
    _output_path_index: dict[str, str] | None = None

    def _build_output_path_index(self) -> dict[str, str]:
        """Build index mapping output_path -> document uri.

        Includes both main outputs and file outputs from {% file %} blocks.
        """
        index: dict[str, str] = {}
        for uri, doc in self.documents.items():
            # Main output
            if doc.output_path is not None:
                index[doc.output_path] = uri
            # File outputs from {% file %} blocks
            for file_path in doc.file_outputs:
                index[file_path] = uri
        return index

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

    def get_llm_call(
        self, doc_uri: str, call_id: str, config_hash: str | None = None
    ) -> LLMCall | None:
        """Get a cached LLM call for a document.

        Args:
            doc_uri: Document URI to look up.
            call_id: The call ID to find.
            config_hash: If provided, only return call if config_hash matches.
                This ensures previous_output is only used when provider config
                hasn't changed.

        Returns:
            The LLMCall if found (and config matches), None otherwise.
        """
        doc = self.get_document(doc_uri)
        if doc is None:
            return None
        call = doc.llm_calls.get(call_id)
        if call is None:
            return None
        # If config_hash provided, validate it matches
        if config_hash is not None and call.config_hash != config_hash:
            return None
        return call

    def get_llm_call_by_position(
        self, doc_uri: str, position_id: str, config_hash: str | None = None
    ) -> LLMCall | None:
        """Get the most recent successful LLM call at a position.

        Used for previous_output lookup. Finds any previous output at the same
        position (regardless of inputs), enabling the LLM to compare and
        potentially return "UseExisting".

        Args:
            doc_uri: Document URI to look up.
            position_id: Position-based ID (e.g., "llm_1_5" or "llm_1_5:0").
            config_hash: If provided, only return call if config_hash matches.

        Returns:
            The most recent successful LLMCall at this position, or None.
        """
        doc = self.get_document(doc_uri)
        if doc is None:
            return None

        # Find all calls at this position
        matching_calls = []
        for call in doc.llm_calls.values():
            if call.position_id != position_id:
                continue
            if not call.is_successful:
                continue
            if config_hash is not None and call.config_hash != config_hash:
                continue
            matching_calls.append(call)

        if not matching_calls:
            return None

        # Return most recent by created_at
        return max(matching_calls, key=lambda c: c.created_at)


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

    file_outputs: dict[str, str] = Field(default_factory=dict)
    """Content of files created via {% file %} blocks (path -> content)."""

    file_output_meta: dict[str, FileOutputMeta] = Field(default_factory=dict)
    """Metadata for file outputs (path -> publish/format/sections info)."""
