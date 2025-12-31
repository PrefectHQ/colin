"""Compile context for tracking refs and LLM calls."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from colin.compiler.state import OperationState, Status
from colin.exceptions import RefNotFoundError
from colin.models import CompiledDocument, LLMCall, RefResult
from colin.providers.manager import ProviderManager
from colin.providers.referenceable import Referenceable

if TYPE_CHECKING:
    from colin.models import Manifest
    from colin.providers.project import ProjectProvider


def _strip_scheme(uri: str) -> str:
    """Strip URI scheme prefix for cleaner display."""
    if "://" in uri:
        return uri.split("://", 1)[1]
    return uri


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
        provider_manager: ProviderManager | None = None,
        doc_state: OperationState | None = None,
    ) -> None:
        """Initialize the compile context.

        Args:
            manifest: The manifest for caching and metadata.
            document_uri: URI of the document being compiled.
            project_provider: Provider for reading compiled outputs (refs).
            compiled_outputs: Already-compiled documents from current run.
            provider_manager: Provider manager for external schemes.
            doc_state: Optional state for progress tracking.
        """
        self.manifest = manifest
        self.document_uri = document_uri
        self.project_provider = project_provider
        self.compiled_outputs = compiled_outputs or {}
        self.provider_manager = provider_manager or ProviderManager()
        self.doc_state = doc_state

        # Tracking during render
        self.refs_evaluated: list[str] = []
        self.llm_calls: dict[str, LLMCall] = {}
        self.total_cost: float = 0.0

    async def ref(self, target: str | Referenceable) -> RefResult:
        """Fetch content from a referenced document or referenceable object.

        This:
        1. Handles referenceable objects by calling to_ref_result()
        2. Normalizes shorthand refs to project:// URIs
        3. Records the dependency edge
        4. Returns the compiled content of the referenced document

        Shorthand URIs (e.g., 'data') are normalized to project://data.md.

        Args:
            target: URI string or object implementing Referenceable protocol.

        Returns:
            RefResult with content and metadata.

        Raises:
            RefNotFoundError: If the referenced document doesn't exist.
        """
        # Handle referenceable objects (e.g., MCPResource, MCPPrompt)
        if isinstance(target, Referenceable):
            result = target.to_ref_result()
            self.track_ref(result.uri)
            return result

        # Normalize shorthand refs to project:// URIs
        uri = self._normalize_uri(target)
        scheme, path = self._split_uri(uri)

        # Record the dependency (only track first ref to each URI)
        is_first_ref = uri not in self.refs_evaluated
        if is_first_ref:
            self.refs_evaluated.append(uri)

        if scheme == "project":
            # Check in-memory compiled outputs first (from current compile run)
            if uri in self.compiled_outputs:
                compiled = self.compiled_outputs[uri]
                name_val = compiled.frontmatter.metadata.get("name")
                desc_val = compiled.frontmatter.metadata.get("description")
                # Track as completed ref (no processing needed for in-memory)
                if is_first_ref and self.doc_state is not None:
                    op = self.doc_state.child("ref", detail=_strip_scheme(uri))
                    op.status = Status.DONE
                return RefResult(
                    name=name_val if isinstance(name_val, str) else uri.split("/")[-1],
                    description=desc_val if isinstance(desc_val, str) else None,
                    content=compiled.output,
                    template="",  # Not needed for in-memory refs
                    updated=datetime.now(timezone.utc),
                    uri=uri,
                )

            # Fetch from storage via project provider
            async def fetch_from_provider() -> RefResult:
                try:
                    content = await self.project_provider.read(uri)
                except FileNotFoundError as e:
                    raise RefNotFoundError(f"Referenced document not found: {uri}") from e

                # Get actual compiled_at timestamp from manifest (or now if unavailable)
                last_updated = await self.project_provider.get_last_updated(uri)
                updated = last_updated or datetime.now(timezone.utc)

                # Create RefResult from raw content
                return RefResult(
                    name=path.split("/")[-1],  # Filename from path
                    description=None,
                    content=content,
                    template="",
                    updated=updated,
                    uri=uri,
                )

            if is_first_ref and self.doc_state is not None:
                with self.doc_state.child("ref", detail=_strip_scheme(uri)):
                    return await fetch_from_provider()
            return await fetch_from_provider()

        async def fetch_external() -> RefResult:
            try:
                provider = self.provider_manager.get_provider(scheme)
            except KeyError as e:
                raise ValueError(f"No provider registered for scheme '{scheme}'") from e
            try:
                content = await provider.read(uri)
            except FileNotFoundError as e:
                raise RefNotFoundError(f"Referenced document not found: {uri}") from e

            # Get actual timestamp from provider (or now if unavailable)
            last_updated = await provider.get_last_updated(uri)
            updated = last_updated or datetime.now(timezone.utc)

            name = path.split("/")[-1] or uri
            return RefResult(
                name=name,
                description=None,
                content=content,
                template="",
                updated=updated,
                uri=uri,
            )

        if is_first_ref and self.doc_state is not None:
            with self.doc_state.child("ref", detail=_strip_scheme(uri)):
                return await fetch_external()
        return await fetch_external()

    def _normalize_uri(self, uri: str) -> str:
        """Normalize a URI to project:// format.

        Converts shorthand refs like 'data' to 'project://data.md'.
        """
        if "://" in uri:
            return uri
        if not uri.endswith(".md"):
            uri = f"{uri}.md"
        return f"project://{uri}"

    def _split_uri(self, uri: str) -> tuple[str, str]:
        """Split a URI into scheme and path."""
        scheme, path = uri.split("://", 1)
        return scheme, path

    def track_ref(self, uri: str) -> None:
        """Record a ref dependency without fetching content."""
        if uri not in self.refs_evaluated:
            self.refs_evaluated.append(uri)

    def add_llm_call(self, call: LLMCall) -> None:
        """Record an LLM call made during compilation.

        Args:
            call: The LLM call to record.
        """
        self.llm_calls[call.call_id] = call
        self.total_cost += call.cost_usd
