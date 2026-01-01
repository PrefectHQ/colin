"""Compile context for tracking refs and LLM calls."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, TypeVar, cast, overload

from colin.compiler.state import OperationState, Status
from colin.exceptions import RefNotFoundError
from colin.models import Address, CompiledDocument, LLMCall
from colin.providers.addressable import Addressable
from colin.providers.file import FileResource
from colin.providers.project import ProjectResource

if TYPE_CHECKING:
    from colin.models import Manifest
    from colin.providers.project import ProjectProvider

T = TypeVar("T", bound=Addressable)


class CompileContext:
    """Tracks state during document compilation.

    Provides ref() implementation and tracks dependencies and LLM calls.
    """

    def __init__(
        self,
        manifest: Manifest,
        document_uri: str,
        project_provider: ProjectProvider,
        compiled_outputs: dict[str, CompiledDocument] | None = None,
        doc_state: OperationState | None = None,
    ) -> None:
        """Initialize the compile context.

        Args:
            manifest: The manifest for caching and metadata.
            document_uri: URI of the document being compiled.
            project_provider: Provider for reading compiled outputs (refs).
            compiled_outputs: Already-compiled documents from current run.
            doc_state: Optional state for progress tracking.
        """
        self.manifest = manifest
        self.document_uri = document_uri
        self.project_provider = project_provider
        self.compiled_outputs = compiled_outputs or {}
        self.doc_state = doc_state

        # Tracking during render
        self.refs_evaluated: list[Address] = []
        self.llm_calls: dict[str, LLMCall] = {}
        self.total_cost: float = 0.0

    @overload
    async def ref(self, target: str) -> FileResource: ...

    @overload
    async def ref(self, target: T) -> T: ...

    @overload
    async def ref(self, target: Coroutine[Any, Any, T]) -> T: ...

    async def ref(self, target: str | T | Coroutine[Any, Any, T]) -> FileResource | T:
        """Track a dependency and return the addressable resource.

        Usage in templates:
            {{ ref("other-doc") }}                    # Project ref
            {{ ref(s3.get("bucket/key")) }}           # S3 resource, tracked
            {{ ref(mcp.github.resource("...")) }}    # MCP resource, tracked

        For provider resources, wrap the provider call in ref() to track
        it as a dependency. Without ref(), the resource is fetched but
        not tracked for staleness checking.

        Args:
            target: One of:
                - String path: relative path for project refs (e.g., "other-doc")
                - Coroutine: async provider call (e.g., s3.get("..."))
                - Addressable: already-fetched resource to track

        Returns:
            The same type passed in: ProjectResource for strings, T for Addressable/Coroutine[T].

        Raises:
            RefNotFoundError: If the referenced document doesn't exist.
        """
        # Handle coroutines from provider calls (e.g., ref(s3.get("...")))
        if asyncio.iscoroutine(target):
            target = await target

        # Handle addressable objects (e.g., MCPResource, HTTPResource, S3Resource)
        if isinstance(target, Addressable):
            self._track_address(target.address())
            return cast(T, target)

        # String path → project ref
        path = self._normalize_path(target)
        uri = f"project://{path}"

        # Check in-memory compiled outputs first (from current compile run)
        if uri in self.compiled_outputs:
            compiled = self.compiled_outputs[uri]
            name_val = compiled.frontmatter.metadata.get("name")
            desc_val = compiled.frontmatter.metadata.get("description")
            resource = ProjectResource(
                path=path,
                _content=compiled.output,
                name=name_val if isinstance(name_val, str) else path.split("/")[-1],
                description=desc_val if isinstance(desc_val, str) else None,
                _last_updated=datetime.now(timezone.utc),
            )
            is_first = self._track_address(resource.address())
            if is_first and self.doc_state is not None:
                op = self.doc_state.child("ref", detail=path)
                op.status = Status.DONE
            return resource

        # Fetch from storage via project provider
        async def fetch_from_provider() -> ProjectResource:
            try:
                result = await self.project_provider.load_uri(uri)
            except FileNotFoundError as e:
                raise RefNotFoundError(f"Referenced document not found: {path}") from e
            return result

        is_first = self._track_address(
            Address(provider="project", instance="", payload={"path": path})
        )
        if is_first and self.doc_state is not None:
            with self.doc_state.child("ref", detail=path):
                return await fetch_from_provider()
        return await fetch_from_provider()

    def _normalize_path(self, path: str) -> str:
        """Normalize a path for project refs.

        Adds .md extension if missing.
        """
        if not path.endswith(".md"):
            path = f"{path}.md"
        return path

    def _track_address(self, addr: Address) -> bool:
        """Record an address as a dependency. Returns True if first time seen."""
        # Use JSON serialization for deduplication
        addr_key = json.dumps(addr, sort_keys=True)
        for existing in self.refs_evaluated:
            if json.dumps(existing, sort_keys=True) == addr_key:
                return False
        self.refs_evaluated.append(addr)
        return True

    def track_ref(self, addr: Address) -> None:
        """Record a ref dependency without fetching content."""
        self._track_address(addr)

    def add_llm_call(self, call: LLMCall) -> None:
        """Record an LLM call made during compilation.

        Args:
            call: The LLM call to record.
        """
        self.llm_calls[call.call_id] = call
        self.total_cost += call.cost_usd
