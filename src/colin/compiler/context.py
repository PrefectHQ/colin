"""Compile context for tracking refs and LLM calls."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from colin.exceptions import RefNotFoundError
from colin.models import CompiledDocument, LLMCall, RefResult

if TYPE_CHECKING:
    from colin.llm.base import LLMProvider
    from colin.models import Manifest
    from colin.plugins.inputs.file import FileInputPlugin


def _has_scheme(uri: str) -> bool:
    """Check if a URI has an explicit scheme (e.g., file://, github://)."""
    return "://" in uri


class CompileContext:
    """Tracks state during document compilation.

    Provides ref() and extract() implementations that record
    dependencies and LLM calls for the manifest.
    """

    def __init__(
        self,
        manifest: Manifest,
        document_uri: str,
        llm_provider: LLMProvider,
        input_plugin: FileInputPlugin,
        compiled_outputs: dict[str, CompiledDocument] | None = None,
    ) -> None:
        """Initialize the compile context.

        Args:
            manifest: The manifest for caching and metadata.
            document_uri: URI of the document being compiled.
            llm_provider: LLM provider for transformations.
            input_plugin: Input plugin for fetching refs.
            compiled_outputs: Already-compiled documents from current run.
        """
        self.manifest = manifest
        self.document_uri = document_uri
        self.llm_provider = llm_provider
        self.input_plugin = input_plugin
        self.compiled_outputs = compiled_outputs or {}

        # Tracking during render
        self.refs_evaluated: list[str] = []
        self.llm_calls: dict[str, LLMCall] = {}
        self.total_cost: float = 0.0

    async def ref(self, uri: str) -> RefResult:
        """Fetch content from a referenced document.

        This:
        1. Validates schemaless refs exist within project (compile-time check)
        2. Records the dependency edge
        3. Returns the compiled content of the referenced document

        Schemaless URIs (e.g., 'reports/summary') must resolve within the
        project boundary - this is validated at compile time. Scheme URIs
        (e.g., 'file://path/to/file') are external references validated
        at runtime.

        Args:
            uri: URI of the document to reference.

        Returns:
            RefResult with content and metadata.

        Raises:
            RefNotFoundError: If the referenced document doesn't exist.
        """
        # Validate schemaless refs exist within project (compile-time guard)
        if not _has_scheme(uri):
            model_path = self.input_plugin.uri_to_model_path(uri)
            if model_path is None:
                raise RefNotFoundError(
                    f"Referenced document '{uri}' not found in project. "
                    f"Schemaless refs must resolve within the project boundary."
                )

        # Record the dependency
        if uri not in self.refs_evaluated:
            self.refs_evaluated.append(uri)

        # Check in-memory compiled outputs first (from current compile run)
        if uri in self.compiled_outputs:
            compiled = self.compiled_outputs[uri]
            name_val = compiled.frontmatter.metadata.get("name")
            desc_val = compiled.frontmatter.metadata.get("description")
            return RefResult(
                name=name_val if isinstance(name_val, str) else uri.split("/")[-1],
                description=desc_val if isinstance(desc_val, str) else None,
                content=compiled.output,
                template="",  # Not needed for in-memory refs
                updated=datetime.now(timezone.utc),
                uri=uri,
            )

        # Fall back to fetching from disk
        try:
            return await self.input_plugin.fetch(uri)
        except FileNotFoundError as e:
            raise RefNotFoundError(f"Referenced document not found: {uri}") from e

    async def extract(
        self,
        content: str,
        prompt: str,
        call_id: str | None = None,
    ) -> str:
        """Extract information from content using LLM.

        Args:
            content: The content to extract from.
            prompt: What to extract.
            call_id: Optional manual ID for caching.

        Returns:
            The extracted text.
        """
        # Determine call ID
        effective_id = call_id or f"auto:{self._hash(content + 'extract' + prompt)}"

        # Check cache
        cached = self._get_cached_llm_call(effective_id, content)
        if cached:
            self.llm_calls[effective_id] = cached  # Preserve in manifest
            return cached.output

        # Get previous output for stability
        previous_output = None
        if call_id:  # Only use previous for manual IDs
            doc_meta = self.manifest.get_document(self.document_uri)
            if doc_meta and effective_id in doc_meta.llm_calls:
                previous_output = doc_meta.llm_calls[effective_id].output

        # Call LLM
        result = await self.llm_provider.extract(content, prompt, previous_output)

        # Record call
        llm_call = LLMCall(
            call_id=effective_id,
            input_hash=self._hash(content),
            output_hash=self._hash(result.text),
            output=result.text,
            model=result.model,
            cost_usd=result.cost,
        )
        self.llm_calls[effective_id] = llm_call
        self.total_cost += result.cost

        return result.text

    async def call_llm_block(
        self,
        body: str,
        model: str,
        call_id: str | None,
    ) -> str:
        """Handle {% llm %}...{% endllm %} block.

        Args:
            body: The rendered block content (prompt).
            model: Model name (ignored for stub).
            call_id: Optional manual ID.

        Returns:
            The LLM response.
        """
        effective_id = call_id or f"auto:{self._hash(body)}"

        # Check cache
        cached = self._get_cached_llm_call(effective_id, body)
        if cached:
            self.llm_calls[effective_id] = cached  # Preserve in manifest
            return cached.output

        # Get previous output for stability
        previous_output = None
        if call_id:  # Only use previous for manual IDs
            doc_meta = self.manifest.get_document(self.document_uri)
            if doc_meta and effective_id in doc_meta.llm_calls:
                previous_output = doc_meta.llm_calls[effective_id].output

        # Build full prompt with previous output if available
        full_prompt = body
        if previous_output:
            full_prompt = (
                f"{body}\n\n"
                f"[Previous output for reference - maintain stability if appropriate:]\n"
                f"{previous_output}"
            )

        # Call LLM
        result = await self.llm_provider.complete(full_prompt, model=model)

        # Record call
        llm_call = LLMCall(
            call_id=effective_id,
            input_hash=self._hash(body),
            output_hash=self._hash(result.text),
            output=result.text,
            model=result.model,
            cost_usd=result.cost,
        )
        self.llm_calls[effective_id] = llm_call
        self.total_cost += result.cost

        return result.text

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
