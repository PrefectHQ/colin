"""Compile context for tracking refs and LLM calls."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pydantic_ai import Agent

from colin.compiler.state import OperationState
from colin.exceptions import RefNotFoundError
from colin.llm.prompts import render_complete_prompt, render_extract_prompt
from colin.llm.types import LLMOutput, UseExisting
from colin.models import CompiledDocument, LLMCall, RefResult

if TYPE_CHECKING:
    from colin.mcp import MCPManager
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
        default_model: str,
        input_plugin: FileInputPlugin,
        compiled_outputs: dict[str, CompiledDocument] | None = None,
        mcp_manager: MCPManager | None = None,
        doc_state: OperationState | None = None,
    ) -> None:
        """Initialize the compile context.

        Args:
            manifest: The manifest for caching and metadata.
            document_uri: URI of the document being compiled.
            default_model: Default LLM model to use.
            input_plugin: Input plugin for fetching refs.
            compiled_outputs: Already-compiled documents from current run.
            mcp_manager: MCP manager for server connections.
            doc_state: Optional state for progress tracking.
        """
        self.manifest = manifest
        self.document_uri = document_uri
        self.default_model = default_model
        self.input_plugin = input_plugin
        self.compiled_outputs = compiled_outputs or {}
        self.mcp_manager = mcp_manager
        self.doc_state = doc_state

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

        # Record the dependency (and track in state tree on first occurrence)
        ref_op = None
        if uri not in self.refs_evaluated:
            self.refs_evaluated.append(uri)
            # Only track first ref to each URI
            if self.doc_state is not None:
                ref_op = self.doc_state.child(f"ref:{uri}")
                ref_op.start()

        # Check in-memory compiled outputs first (from current compile run)
        if uri in self.compiled_outputs:
            compiled = self.compiled_outputs[uri]
            name_val = compiled.frontmatter.metadata.get("name")
            desc_val = compiled.frontmatter.metadata.get("description")
            if ref_op is not None:
                ref_op.ref()
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
            result = await self.input_plugin.fetch(uri)
            if ref_op is not None:
                ref_op.ref()
            return result
        except FileNotFoundError as e:
            if ref_op is not None:
                ref_op.fail(str(e))
            raise RefNotFoundError(f"Referenced document not found: {uri}") from e

    async def extract(
        self,
        content: str,
        prompt: str,
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
            # Track cached call in state tree
            if self.doc_state is not None:
                op_state = self.doc_state.child(f"extract:{effective_id}")
                op_state.cached()
            return cached_call.output

        # Get previous output for stability
        previous_output = None
        if call_id:  # Only use previous for manual IDs
            doc_meta = self.manifest.get_document(self.document_uri)
            if doc_meta and effective_id in doc_meta.llm_calls:
                previous_output = doc_meta.llm_calls[effective_id].output

        # Render prompt from template
        full_prompt = render_extract_prompt(content, prompt, previous_output)

        # Create state for this operation
        op_state = None
        if self.doc_state is not None:
            op_state = self.doc_state.child(f"extract:{effective_id}", detail=effective_model)
            op_state.start()

        # Call LLM with structured output
        agent: Agent[None, LLMOutput] = Agent(
            effective_model,
            output_type=[UseExisting, str],  # type: ignore[arg-type]
        )
        result = await agent.run(full_prompt)

        # Handle UseExisting
        if isinstance(result.output, UseExisting):
            if previous_output is None:
                raise ValueError("LLM returned UseExisting but no previous output exists")
            output_text = previous_output
        else:
            output_text = str(result.output)

        # Get cost from result
        cost = 0.0
        usage = result.usage()
        if usage:
            # Pydantic AI provides token counts, we'd need a pricing table
            # For now, use 0.0 - can add cost calculation later
            pass

        # Record call
        llm_call = LLMCall(
            call_id=effective_id,
            input_hash=self._hash(content),
            output_hash=self._hash(output_text),
            output=output_text,
            model=effective_model,
            cost_usd=cost,
        )
        self.llm_calls[effective_id] = llm_call
        self.total_cost += cost

        # Mark operation as done
        if op_state is not None:
            op_state.done()

        return output_text

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
            # Track cached call in state tree
            if self.doc_state is not None:
                op_state = self.doc_state.child(f"llm:{effective_id}")
                op_state.cached()
            return cached_call.output

        # Get previous output for stability
        previous_output = None
        if call_id:  # Only use previous for manual IDs
            doc_meta = self.manifest.get_document(self.document_uri)
            if doc_meta and effective_id in doc_meta.llm_calls:
                previous_output = doc_meta.llm_calls[effective_id].output

        # Render prompt from template
        full_prompt = render_complete_prompt(body, previous_output)

        # Create state for this operation
        op_state = None
        if self.doc_state is not None:
            op_state = self.doc_state.child(f"llm:{effective_id}", detail=effective_model)
            op_state.start()

        # Call LLM with structured output
        agent: Agent[None, LLMOutput] = Agent(
            effective_model,
            output_type=[UseExisting, str],  # type: ignore[arg-type]
        )
        result = await agent.run(full_prompt)

        # Handle UseExisting
        if isinstance(result.output, UseExisting):
            if previous_output is None:
                raise ValueError("LLM returned UseExisting but no previous output exists")
            output_text = previous_output
        else:
            output_text = str(result.output)

        # Get cost from result
        cost = 0.0
        usage = result.usage()
        if usage:
            # Cost calculation would go here
            pass

        # Record call
        llm_call = LLMCall(
            call_id=effective_id,
            input_hash=self._hash(body),
            output_hash=self._hash(output_text),
            output=output_text,
            model=effective_model,
            cost_usd=cost,
        )
        self.llm_calls[effective_id] = llm_call
        self.total_cost += cost

        # Mark operation as done
        if op_state is not None:
            op_state.done()

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

    async def mcp_resource(self, server: str, uri: str) -> str:
        """Read a resource from an MCP server.

        Args:
            server: Server name as configured in colin.toml.
            uri: Resource URI.

        Returns:
            Resource content as string.

        Raises:
            ValueError: If MCP manager not configured or server unknown.
        """
        if self.mcp_manager is None:
            raise ValueError("No MCP servers configured")
        return await self.mcp_manager.read_resource(server, uri)
