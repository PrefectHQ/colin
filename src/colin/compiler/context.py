"""Compile context for tracking refs and LLM calls."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any, TypeVar, cast, overload

from colin.compiler.state import OperationState, Status
from colin.exceptions import RefNotFoundError
from colin.models import CompiledDocument, LLMCall, Ref
from colin.providers.resource import Resource

if TYPE_CHECKING:
    from colin.models import Manifest
    from colin.providers.project import ProjectProvider, ProjectResource

T = TypeVar("T", bound=Resource)


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
        self.refs: list[Ref] = []
        self.ref_versions: dict[str, str] = {}  # ref.key() -> version
        self.llm_calls: dict[str, LLMCall] = {}
        self.total_cost: float = 0.0

    @overload
    async def ref(self, target: str) -> ProjectResource: ...

    @overload
    async def ref(self, target: T) -> T: ...

    @overload
    async def ref(self, target: Coroutine[Any, Any, T]) -> T: ...

    async def ref(self, target: str | T | Coroutine[Any, Any, T]) -> ProjectResource | T:
        """Track a dependency and return the resource.

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
                - Resource: already-fetched resource to track

        Returns:
            The same type passed in: ProjectResource for strings, T for Resource/Coroutine[T].

        Raises:
            RefNotFoundError: If the referenced document doesn't exist.
        """
        # Import here to avoid circular imports
        from colin.providers.project import ProjectResource

        # Handle coroutines from provider calls (e.g., ref(s3.get("...")))
        if asyncio.iscoroutine(target):
            target = await target

        # Handle Resource objects (e.g., MCPResource, HTTPResource, S3Resource)
        if isinstance(target, Resource):
            self.track(target.ref(), target.version)
            return cast(T, target)

        # String path → exact output filename (no normalization)
        path = target

        # Check in-memory compiled outputs first (keyed by output_path)
        compiled = self.compiled_outputs.get(path)

        if compiled is not None:
            name_val = compiled.frontmatter.metadata.get("name")
            desc_val = compiled.frontmatter.metadata.get("description")

            project_ref = Ref(
                provider="project",
                connection="",
                method="get",
                args={"path": path},
            )
            resource = ProjectResource(
                content=compiled.output,
                ref=project_ref,
                relative_path=path,
                target_path=self.project_provider.target_path or self.project_provider.base_path,
                is_private=compiled.is_private,
                name=name_val if isinstance(name_val, str) else path.split("/")[-1],
                description=desc_val if isinstance(desc_val, str) else None,
                output_hash=compiled.output_hash,
            )
            is_first = self.track(resource.ref(), resource.version)
            if is_first and self.doc_state is not None:
                op = self.doc_state.child("ref", detail=path)
                op.status = Status.DONE
            return resource

        # Fetch from storage via project provider
        async def fetch_from_provider() -> ProjectResource:
            try:
                result = await self.project_provider.get(path)
            except FileNotFoundError as e:
                raise RefNotFoundError(f"Referenced document not found: {path}") from e
            return result

        project_ref = Ref(
            provider="project",
            connection="",
            method="get",
            args={"path": path},
        )
        # Check if this is a new ref so we can show progress indicator
        is_first = project_ref.key() not in self.ref_versions
        if is_first and self.doc_state is not None:
            with self.doc_state.child("ref", detail=path):
                result = await fetch_from_provider()
                self.track(result.ref(), result.version)
                return result
        result = await fetch_from_provider()
        self.track(result.ref(), result.version)
        return result

    def track(self, ref: Ref, version: str) -> bool:
        """Record a ref and its version as a dependency.

        Args:
            ref: The Ref to track.
            version: The current version of the resource.

        Returns:
            True if this is the first time seeing this ref.
        """
        key = ref.key()
        if key in self.ref_versions:
            return False
        self.refs.append(ref)
        self.ref_versions[key] = version
        return True

    def add_llm_call(self, call: LLMCall) -> None:
        """Record an LLM call made during compilation.

        Args:
            call: The LLM call to record.
        """
        self.llm_calls[call.call_id] = call
        self.total_cost += call.cost_usd
