"""Compile context for tracking refs and LLM calls."""

from __future__ import annotations

import hashlib
import json
from contextlib import nullcontext as _nullcontext
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from pydantic_ai import Agent

from colin.compiler.state import OperationState, Status
from colin.exceptions import RefNotFoundError
from colin.llm.prompts import render_classify_prompt, render_complete_prompt, render_extract_prompt
from colin.llm.types import LLMOutput, UseExisting, create_classification_model
from colin.models import CompiledDocument, LLMCall, RefResult
from colin.providers.manager import ProviderManager
from colin.providers.referenceable import Referenceable

if TYPE_CHECKING:
    from colin.models import Manifest
    from colin.providers.project import ProjectProvider


def _truncate(text: str, max_len: int = 40) -> str:
    """Truncate text for display, collapsing whitespace."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= max_len:
        return f"'{collapsed}'"
    return f"'{collapsed[: max_len - 3]}...'"


def _strip_scheme(uri: str) -> str:
    """Strip URI scheme prefix for cleaner display."""
    if "://" in uri:
        return uri.split("://", 1)[1]
    return uri


class CompileContext:
    """Tracks state during document compilation.

    Provides ref() and extract() implementations that record
    dependencies and LLM calls for the manifest.
    """

    def __init__(
        self,
        manifest: Manifest,
        document_uri: str,
        default_model: str,
        project_provider: ProjectProvider,
        compiled_outputs: dict[str, CompiledDocument] | None = None,
        provider_manager: ProviderManager | None = None,
        doc_state: OperationState | None = None,
    ) -> None:
        """Initialize the compile context.

        Args:
            manifest: The manifest for caching and metadata.
            document_uri: URI of the document being compiled.
            default_model: Default LLM model to use.
            project_provider: Provider for reading compiled outputs (refs).
            compiled_outputs: Already-compiled documents from current run.
            provider_manager: Provider manager for external schemes.
            doc_state: Optional state for progress tracking.
        """
        self.manifest = manifest
        self.document_uri = document_uri
        self.default_model = default_model
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

    async def extract(
        self,
        content: str,
        prompt: str,
        *,
        call_id: str | None = None,
        model: str | None = None,
    ) -> str:
        """Extract information from content using LLM.

        Args:
            content: The content to extract from.
            prompt: What to extract.
            call_id: Optional manual ID for caching.
            model: Optional model override.

        Returns:
            The extracted text.
        """
        # Determine call ID
        effective_id = call_id or f"auto:{self._hash(content + 'extract' + prompt)}"
        effective_model = model or self.default_model

        # Check cache
        cached_call = self._get_cached_llm_call(effective_id, content)
        if cached_call:
            self.llm_calls[effective_id] = cached_call  # Preserve in manifest
            if self.doc_state is not None:
                op = self.doc_state.child("ctx", detail=f"extract({_truncate(prompt)})")
                op.mark_cached()
            return cached_call.output

        # Get previous output for stability
        previous_output = None
        if call_id:  # Only use previous for manual IDs
            doc_meta = self.manifest.get_document(self.document_uri)
            if doc_meta and effective_id in doc_meta.llm_calls:
                previous_output = doc_meta.llm_calls[effective_id].output

        # Render prompt from template
        full_prompt = render_extract_prompt(content, prompt, previous_output)

        # Call LLM (with state tracking if enabled)
        op = (
            self.doc_state.child("ctx", detail=f"extract({_truncate(prompt)})")
            if self.doc_state
            else None
        )
        with op if op else _nullcontext():
            # Only allow UseExisting if there's a previous output to use
            output_type: list[type] = [UseExisting, str] if previous_output else [str]
            agent: Agent[None, LLMOutput] = Agent(
                effective_model,
                output_type=output_type,  # type: ignore[arg-type]
            )
            result = await agent.run(full_prompt)

            # Handle UseExisting
            if isinstance(result.output, UseExisting):
                assert previous_output is not None  # Guarded by output_type conditional
                output_text = previous_output
            else:
                output_text = str(result.output)

            # Record call
            llm_call = LLMCall(
                call_id=effective_id,
                input_hash=self._hash(content),
                output_hash=self._hash(output_text),
                output=output_text,
                model=effective_model,
                cost_usd=0.0,
            )
            self.llm_calls[effective_id] = llm_call

            return output_text

    async def classify(
        self,
        content: str,
        labels: list[str | bool],
        *,
        call_id: str | None = None,
        model: str | None = None,
        multi: bool = False,
    ) -> str | bool | list[str | bool]:
        """Classify content into one or more predefined labels using LLM.

        Args:
            content: The content to classify.
            labels: List of valid labels to choose from.
            call_id: Optional manual ID for caching.
            model: Optional model override.
            multi: Whether to allow multiple labels (multi-label classification).

        Returns:
            Single label (str or bool) if multi=False, list of labels if multi=True.

        Raises:
            ValueError: If the LLM returns an invalid label.
        """
        if not labels:
            raise ValueError("Labels list cannot be empty")

        # Sort labels for consistent hashing (convert bools to strings for sorting)
        sorted_labels = sorted(labels, key=lambda x: (isinstance(x, bool), str(x)))
        labels_key = ",".join(str(label) for label in sorted_labels)

        # Determine call ID
        effective_id = (
            call_id or f"auto:{self._hash(content + 'classify' + labels_key + str(multi))}"
        )
        effective_model = model or self.default_model

        # Check cache
        cached_call = self._get_cached_llm_call(effective_id, content)
        if cached_call:
            self.llm_calls[effective_id] = cached_call  # Preserve in manifest
            if self.doc_state is not None:
                labels_display = ",".join(sorted_labels[:3])
                if len(sorted_labels) > 3:
                    labels_display += "..."
                op = self.doc_state.child("ctx", detail=f"classify({labels_display})")
                op.mark_cached()
            # Parse cached output - could be string or JSON list
            cached_output = cached_call.output
            if multi:
                # Try to parse as JSON list, fallback to single-item list
                try:
                    parsed = json.loads(cached_output)
                    if isinstance(parsed, list):
                        return parsed
                    return [parsed] if parsed else []
                except (json.JSONDecodeError, TypeError):
                    return [cached_output] if cached_output else []
            return cached_output

        # Get previous output for stability
        previous_output = None
        if call_id:  # Only use previous for manual IDs
            doc_meta = self.manifest.get_document(self.document_uri)
            if doc_meta and effective_id in doc_meta.llm_calls:
                previous_output = doc_meta.llm_calls[effective_id].output

        # Render prompt from template
        full_prompt = render_classify_prompt(content, sorted_labels, previous_output, multi)

        # Create classification model for structured output
        ClassificationModel = create_classification_model(sorted_labels, multi)

        # Call LLM (with state tracking if enabled)
        labels_display = ",".join(sorted_labels[:3])
        if len(sorted_labels) > 3:
            labels_display += "..."
        op = (
            self.doc_state.child("ctx", detail=f"classify({labels_display})")
            if self.doc_state
            else None
        )
        with op if op else _nullcontext():
            # Only allow UseExisting if there's a previous output to use
            output_type: list[type] = (
                [UseExisting, ClassificationModel] if previous_output else [ClassificationModel]
            )
            agent: Agent[None, Any] = Agent(  # type: ignore[assignment]
                effective_model,
                output_type=output_type,  # type: ignore[arg-type]
            )
            result = await agent.run(full_prompt)

            # Handle UseExisting
            if isinstance(result.output, UseExisting):
                assert previous_output is not None  # Guarded by output_type conditional
                output_text = previous_output
                # Parse previous output
                if multi:
                    try:
                        parsed = json.loads(output_text)
                        if isinstance(parsed, list):
                            output_value = parsed
                        else:
                            output_value = [parsed] if parsed else []
                    except (json.JSONDecodeError, TypeError):
                        output_value = [output_text] if output_text else []
                    return output_value
                return output_text

            # Extract label(s) from structured output
            if multi:
                output_value = result.output.labels  # type: ignore[attr-defined]
            else:
                output_value = result.output.label  # type: ignore[attr-defined]

            # Record call (store as JSON for multi-label)
            if multi:
                record_output = (
                    json.dumps(output_value)
                    if isinstance(output_value, list)
                    else str(output_value)
                )
            else:
                record_output = str(output_value)

            llm_call = LLMCall(
                call_id=effective_id,
                input_hash=self._hash(content),
                output_hash=self._hash(record_output),
                output=record_output,
                model=effective_model,
                cost_usd=0.0,
            )
            self.llm_calls[effective_id] = llm_call

            return output_value

    async def call_llm_block(
        self,
        body: str,
        model: str | None,
        call_id: str | None,
    ) -> str:
        """Handle {% llm %}...{% endllm %} block.

        Args:
            body: The rendered block content (prompt).
            model: Model name override.
            call_id: Optional manual ID.

        Returns:
            The LLM response.
        """
        effective_id = call_id or f"auto:{self._hash(body)}"
        effective_model = model or self.default_model

        # Check cache
        cached_call = self._get_cached_llm_call(effective_id, body)
        if cached_call:
            self.llm_calls[effective_id] = cached_call  # Preserve in manifest
            if self.doc_state is not None:
                op = self.doc_state.child("ctx", detail=f"llm({_truncate(body)})")
                op.mark_cached()
            return cached_call.output

        # Get previous output for stability
        previous_output = None
        if call_id:  # Only use previous for manual IDs
            doc_meta = self.manifest.get_document(self.document_uri)
            if doc_meta and effective_id in doc_meta.llm_calls:
                previous_output = doc_meta.llm_calls[effective_id].output

        # Render prompt from template
        full_prompt = render_complete_prompt(body, previous_output)

        # Call LLM (with state tracking if enabled)
        op = (
            self.doc_state.child("ctx", detail=f"llm({_truncate(body)})")
            if self.doc_state
            else None
        )
        with op if op else _nullcontext():
            # Only allow UseExisting if there's a previous output to use
            output_type: list[type] = [UseExisting, str] if previous_output else [str]
            agent: Agent[None, LLMOutput] = Agent(
                effective_model,
                output_type=output_type,  # type: ignore[arg-type]
            )
            result = await agent.run(full_prompt)

            # Handle UseExisting
            if isinstance(result.output, UseExisting):
                assert previous_output is not None  # Guarded by output_type conditional
                output_text = previous_output
            else:
                output_text = str(result.output)

            # Record call
            llm_call = LLMCall(
                call_id=effective_id,
                input_hash=self._hash(body),
                output_hash=self._hash(output_text),
                output=output_text,
                model=effective_model,
                cost_usd=0.0,
            )
            self.llm_calls[effective_id] = llm_call

            return output_text

    def _get_cached_llm_call(self, call_id: str, current_input: str) -> LLMCall | None:
        """Check if we have a valid cached LLM call.

        Args:
            call_id: The call ID to check.
            current_input: The current input content.

        Returns:
            Cached LLMCall if valid, None otherwise.
        """
        doc_meta = self.manifest.get_document(self.document_uri)
        if doc_meta is None:
            return None

        cached = doc_meta.llm_calls.get(call_id)
        if cached and cached.input_hash == self._hash(current_input):
            return cached
        return None

    def _hash(self, content: str) -> str:
        """Hash content for caching.

        Args:
            content: Content to hash.

        Returns:
            16-character hash string.
        """
        return hashlib.sha256(content.encode()).hexdigest()[:16]
