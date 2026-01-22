"""LLM provider functions for templates."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from contextlib import nullcontext as _nullcontext
from typing import Any, ClassVar

from pydantic import model_validator
from pydantic_ai import Agent
from pydantic_ai.models import Model, infer_model

from colin.compiler.cache import _serialize_value, cached, get_compile_context, hash_args
from colin.llm.prompts import render_classify_prompt, render_complete_prompt, render_extract_prompt
from colin.llm.types import LLMOutput, create_classification_model
from colin.models import LLMCall
from colin.providers.base import Provider
from colin.settings import settings


def _truncate(text: str, max_len: int = 40) -> str:
    """Truncate text for display, collapsing whitespace."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= max_len:
        return f"'{collapsed}'"
    return f"'{collapsed[: max_len - 3]}...'"


class LLMProvider(Provider):
    """Provider for LLM template functions.

    Template usage:
        {{ colin.llm.complete("Write a haiku about...") }}
        {{ colin.llm.classify("Is this positive?", ["positive", "negative"]) }}

    Configuration via colin.toml:
        [[providers.llm]]
        model = "openai:gpt-4o"  # Override default model
    """

    namespace: ClassVar[str] = "llm"

    model: str | Model | None = None
    """Model for LLM calls. Falls back to COLIN_DEFAULT_LLM_MODEL env var."""

    instructions: str | None = None
    """Provider-level instructions (system prompt context). Inline string."""

    instructions_ref: str | None = None
    """Provider-level instructions reference. Path relative to project root, compiled via ref()."""

    @model_validator(mode="after")
    def _validate_instructions(self) -> LLMProvider:
        """Validate that only one of instructions or instructions_ref is set."""
        if self.instructions is not None and self.instructions_ref is not None:
            raise ValueError(
                "Cannot set both 'instructions' and 'instructions_ref' on the same LLM provider. "
                "Use only one."
            )
        return self

    async def _resolve_instructions(self, call_level_instructions: str | None = None) -> str | None:
        """Resolve effective instructions with precedence: call-level > provider-level > None.

        Args:
            call_level_instructions: Optional instructions from call site (highest precedence).

        Returns:
            Resolved instructions string, or None if no instructions configured.

        Raises:
            RuntimeError: If instructions_ref is set but compile context is not available.
        """
        # Highest precedence: call-level override
        if call_level_instructions is not None:
            return call_level_instructions

        # Provider-level: inline string
        if self.instructions is not None:
            return self.instructions

        # Provider-level: reference to compiled file
        if self.instructions_ref is not None:
            compile_ctx = get_compile_context()
            if compile_ctx is None:
                raise RuntimeError(
                    f"Cannot resolve instructions_ref '{self.instructions_ref}' "
                    "without compile context."
                )
            # Use ref() to get compiled content
            resource = await compile_ctx.ref(self.instructions_ref)
            if resource is None:
                raise RuntimeError(
                    f"Cannot resolve instructions_ref '{self.instructions_ref}': "
                    "resource not found."
                )
            return resource.content

        return None

    async def load_address(self, payload: dict[str, Any]):
        """LLM provider does not support load_address.

        LLM is a transformation provider that returns raw values (strings, labels),
        not addressable resources. Use the template functions instead.
        """
        raise NotImplementedError(
            "LLM provider does not support load_address - use template functions"
        )

    def get_functions(self) -> dict[str, Callable[..., Awaitable[object]]]:
        return {
            "extract": self._extract,
            "classify": self._classify,
            "complete": self._complete,
        }

    @cached(key="llm.extract", detail_arg="prompt")
    async def _extract(
        self,
        content: object,
        prompt: str,
        model: str | None = None,
        instructions: str | None = None,
        _position_id: str | None = None,
    ) -> str:
        """Extract information from content using LLM.

        Args:
            content: The content to extract from.
            prompt: What to extract.
            model: Optional model override.
            instructions: Optional instructions override (call-level).
            _position_id: Position-based ID (e.g., 'extract_1' or 'extract_1:0' for loops).
                Used for document-scoped caching and previous_output lookup.

        Returns:
            The extracted text.
        """
        serialized = _serialize_value(content)
        effective_model = infer_model(model or self.model or settings.default_llm_model)
        compile_ctx = get_compile_context()
        config_hash = self._config_hash

        # Generate call_id for tracking (unique per invocation)
        input_hash = hash_args((serialized, prompt), {})
        if _position_id:
            call_id = f"llm.extract:{_position_id}:{input_hash}"
        else:
            call_id = f"llm.extract:{input_hash}"

        # Look up previous output by POSITION (not call_id)
        # This finds any previous output at this position, regardless of inputs
        previous_output = None
        if compile_ctx and _position_id:
            prev_call = compile_ctx.manifest.get_llm_call_by_position(
                compile_ctx.document_uri, _position_id, config_hash=config_hash
            )
            if prev_call:
                previous_output = prev_call.output

        # Render prompt from template
        full_prompt = render_extract_prompt(serialized, prompt, previous_output)

        # Resolve effective instructions
        effective_instructions = await self._resolve_instructions(instructions)

        # Call LLM (with state tracking if enabled)
        doc_state = compile_ctx.doc_state if compile_ctx else None
        op = doc_state.child("llm", detail=f"extract({_truncate(prompt)})") if doc_state else None
        with op if op else _nullcontext():
            try:
                output_type: list[type] = [str]
                agent_kwargs: dict[str, Any] = {
                    "output_type": output_type,
                }
                if effective_instructions:
                    agent_kwargs["instructions"] = effective_instructions
                agent: Agent[None, LLMOutput] = Agent(
                    effective_model,
                    **agent_kwargs,
                )
                result = await agent.run(full_prompt)
                output_text = str(result.output)

                # Record LLM call for tracking (only on actual execution, not cache hit)
                if compile_ctx:
                    compile_ctx.add_llm_call(
                        LLMCall(
                            call_id=call_id,
                            position_id=_position_id,
                            config_hash=config_hash,
                            input_hash=hash_args((serialized,), {}),
                            output_hash=hash_args((output_text,), {}),
                            output=output_text,
                            model=effective_model.model_name,
                            cost_usd=0.0,
                        )
                    )

                return output_text

            except Exception as e:
                # Record failed LLM call
                if compile_ctx:
                    compile_ctx.add_llm_call(
                        LLMCall(
                            call_id=call_id,
                            position_id=_position_id,
                            config_hash=config_hash,
                            input_hash=hash_args((serialized,), {}),
                            output_hash="",
                            output="",
                            model=effective_model.model_name,
                            cost_usd=0.0,
                            is_successful=False,
                            error=str(e),
                        )
                    )
                raise

    @cached(key="llm.classify", detail_arg="labels")
    async def _classify(
        self,
        content: object,
        labels: list[str | bool],
        model: str | None = None,
        multi: bool = False,
        instructions: str | None = None,
        _position_id: str | None = None,
    ) -> str | bool | list[str | bool]:
        """Classify content into one or more predefined labels using LLM.

        Args:
            content: The content to classify.
            labels: List of valid labels to choose from.
            model: Optional model override.
            multi: Whether to allow multiple labels (multi-label classification).
            instructions: Optional instructions override (call-level).
            _position_id: Position-based ID (e.g., 'classify_1' or 'classify_1:0' for loops).
                Used for document-scoped caching and previous_output lookup.

        Returns:
            Single label (str or bool) if multi=False, list of labels if multi=True.

        Raises:
            ValueError: If labels list is empty.
        """
        if not labels:
            raise ValueError("Labels list cannot be empty")

        serialized = _serialize_value(content)
        effective_model = infer_model(model or self.model or settings.default_llm_model)
        compile_ctx = get_compile_context()
        config_hash = self._config_hash

        # Sort labels for consistent hashing
        sorted_labels = sorted(labels, key=lambda x: (isinstance(x, bool), str(x)))
        labels_key = ",".join(str(label) for label in sorted_labels)

        # Generate call_id for tracking (unique per invocation)
        input_hash = hash_args((serialized, labels_key, str(multi)), {})
        if _position_id:
            call_id = f"llm.classify:{_position_id}:{input_hash}"
        else:
            call_id = f"llm.classify:{input_hash}"

        # Look up previous output by POSITION (not call_id)
        # This finds any previous output at this position, regardless of inputs
        previous_output = None
        if compile_ctx and _position_id:
            prev_call = compile_ctx.manifest.get_llm_call_by_position(
                compile_ctx.document_uri, _position_id, config_hash=config_hash
            )
            if prev_call:
                previous_output = prev_call.output

        # Render prompt from template
        full_prompt = render_classify_prompt(serialized, sorted_labels, previous_output, multi)

        # Create classification model for structured output
        ClassificationModel = create_classification_model(sorted_labels, multi)

        # Resolve effective instructions
        effective_instructions = await self._resolve_instructions(instructions)

        # Call LLM (with state tracking if enabled)
        doc_state = compile_ctx.doc_state if compile_ctx else None
        labels_display = ",".join(str(lbl) for lbl in sorted_labels[:3])
        if len(sorted_labels) > 3:
            labels_display += "..."
        op = doc_state.child("llm", detail=f"classify({labels_display})") if doc_state else None
        with op if op else _nullcontext():
            try:
                output_type: list[type] = [ClassificationModel]
                agent_kwargs: dict[str, Any] = {
                    "output_type": output_type,
                }
                if effective_instructions:
                    agent_kwargs["instructions"] = effective_instructions
                agent: Agent[None, Any] = Agent(
                    effective_model,
                    **agent_kwargs,
                )
                result = await agent.run(full_prompt)

                # Extract label(s) from structured output
                if multi:
                    output_value = result.output.labels
                else:
                    output_value = result.output.label

                # Record call (store as JSON for multi-label)
                if multi:
                    record_output = (
                        json.dumps(output_value)
                        if isinstance(output_value, list)
                        else str(output_value)
                    )
                else:
                    record_output = str(output_value)

                # Record LLM call for tracking (only on actual execution, not cache hit)
                if compile_ctx:
                    compile_ctx.add_llm_call(
                        LLMCall(
                            call_id=call_id,
                            position_id=_position_id,
                            config_hash=config_hash,
                            input_hash=hash_args((serialized,), {}),
                            output_hash=hash_args((record_output,), {}),
                            output=record_output,
                            model=effective_model.model_name,
                            cost_usd=0.0,
                        )
                    )

                return output_value

            except Exception as e:
                # Record failed LLM call
                if compile_ctx:
                    compile_ctx.add_llm_call(
                        LLMCall(
                            call_id=call_id,
                            position_id=_position_id,
                            config_hash=config_hash,
                            input_hash=hash_args((serialized,), {}),
                            output_hash="",
                            output="",
                            model=effective_model.model_name,
                            cost_usd=0.0,
                            is_successful=False,
                            error=str(e),
                        )
                    )
                raise

    @cached(key="llm.complete", detail_arg="prompt")
    async def _complete(
        self,
        prompt: str,
        model: str | None = None,
        instructions: str | None = None,
        _position_id: str | None = None,
    ) -> str:
        """Complete a prompt using LLM.

        Used for {% llm %}...{% endllm %} blocks.

        Args:
            prompt: The prompt to complete.
            model: Optional model override.
            instructions: Optional instructions override (call-level).
            _position_id: Position-based ID (e.g., 'llm_1_5' or 'llm_1_5:0' for loops).
                Used for document-scoped caching and previous_output lookup.

        Returns:
            The LLM response.
        """
        effective_model = infer_model(model or self.model or settings.default_llm_model)
        compile_ctx = get_compile_context()
        config_hash = self._config_hash

        # Generate call_id for tracking (unique per invocation)
        input_hash = hash_args((prompt,), {})
        if _position_id:
            call_id = f"llm.complete:{_position_id}:{input_hash}"
        else:
            call_id = f"llm.complete:{input_hash}"

        # Look up previous output by POSITION (not call_id)
        # This finds any previous output at this position, regardless of inputs
        previous_output = None
        if compile_ctx and _position_id:
            prev_call = compile_ctx.manifest.get_llm_call_by_position(
                compile_ctx.document_uri, _position_id, config_hash=config_hash
            )
            if prev_call:
                previous_output = prev_call.output

        # Render prompt from template
        full_prompt = render_complete_prompt(prompt, previous_output)

        # Resolve effective instructions
        effective_instructions = await self._resolve_instructions(instructions)

        # Call LLM (with state tracking if enabled)
        doc_state = compile_ctx.doc_state if compile_ctx else None
        op = doc_state.child("llm", detail=f"complete({_truncate(prompt)})") if doc_state else None
        with op if op else _nullcontext():
            try:
                output_type: list[type] = [str]
                agent_kwargs: dict[str, Any] = {
                    "output_type": output_type,
                }
                if effective_instructions:
                    agent_kwargs["instructions"] = effective_instructions
                agent: Agent[None, LLMOutput] = Agent(
                    effective_model,
                    **agent_kwargs,
                )
                result = await agent.run(full_prompt)
                output_text = str(result.output)

                # Record LLM call for tracking (only on actual execution, not cache hit)
                if compile_ctx:
                    compile_ctx.add_llm_call(
                        LLMCall(
                            call_id=call_id,
                            position_id=_position_id,
                            config_hash=config_hash,
                            input_hash=hash_args((prompt,), {}),
                            output_hash=hash_args((output_text,), {}),
                            output=output_text,
                            model=effective_model.model_name,
                            cost_usd=0.0,
                        )
                    )

                return output_text

            except Exception as e:
                # Record failed LLM call
                if compile_ctx:
                    compile_ctx.add_llm_call(
                        LLMCall(
                            call_id=call_id,
                            position_id=_position_id,
                            config_hash=config_hash,
                            input_hash=hash_args((prompt,), {}),
                            output_hash="",
                            output="",
                            model=effective_model.model_name,
                            cost_usd=0.0,
                            is_successful=False,
                            error=str(e),
                        )
                    )
                raise
