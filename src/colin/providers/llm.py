"""LLM provider functions for templates."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from contextlib import nullcontext as _nullcontext
from typing import Any, ClassVar

from pydantic_ai import Agent
from pydantic_ai.models import Model, infer_model

from colin.llm.prompts import render_classify_prompt, render_complete_prompt, render_extract_prompt
from colin.llm.types import LLMOutput, create_classification_model
from colin.models import LLMCall
from colin.providers.base import Provider
from colin.providers.cache import _serialize_value, cached, get_compile_context, hash_args
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

    async def load_address(self, payload: dict[str, Any]):  # type: ignore[override]
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

    @cached(key="llm.extract")
    async def _extract(
        self,
        content: object,
        prompt: str,
        model: str | None = None,
    ) -> str:
        """Extract information from content using LLM.

        Args:
            content: The content to extract from.
            prompt: What to extract.
            model: Optional model override.

        Returns:
            The extracted text.
        """
        serialized = _serialize_value(content)
        effective_model = infer_model(model or self.model or settings.default_llm_model)
        compile_ctx = get_compile_context()

        # Generate call_id for tracking
        call_id = f"llm.extract:{hash_args((serialized, prompt), {})}"

        # TODO: previous_output should enable stability when inputs change,
        # but current auto-ID design ties cache key to input hash.
        # Needs redesign to support "same logical call, different inputs".
        previous_output = None

        # Render prompt from template
        full_prompt = render_extract_prompt(serialized, prompt, previous_output)

        # Call LLM (with state tracking if enabled)
        doc_state = compile_ctx.doc_state if compile_ctx else None
        op = doc_state.child("llm", detail=f"extract({_truncate(prompt)})") if doc_state else None
        with op if op else _nullcontext():
            try:
                output_type: list[type] = [str]
                agent: Agent[None, LLMOutput] = Agent(
                    effective_model,
                    output_type=output_type,  # type: ignore[arg-type]
                )
                result = await agent.run(full_prompt)
                output_text = str(result.output)

                # Record LLM call for tracking (only on actual execution, not cache hit)
                if compile_ctx:
                    compile_ctx.add_llm_call(
                        LLMCall(
                            call_id=call_id,
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

    @cached(key="llm.classify")
    async def _classify(
        self,
        content: object,
        labels: list[str | bool],
        model: str | None = None,
        multi: bool = False,
    ) -> str | bool | list[str | bool]:
        """Classify content into one or more predefined labels using LLM.

        Args:
            content: The content to classify.
            labels: List of valid labels to choose from.
            model: Optional model override.
            multi: Whether to allow multiple labels (multi-label classification).

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

        # Sort labels for consistent hashing
        sorted_labels = sorted(labels, key=lambda x: (isinstance(x, bool), str(x)))
        labels_key = ",".join(str(label) for label in sorted_labels)

        # Generate call_id for tracking
        call_id = f"llm.classify:{hash_args((serialized, labels_key, str(multi)), {})}"

        # TODO: previous_output should enable stability when inputs change,
        # but current auto-ID design ties cache key to input hash.
        # Needs redesign to support "same logical call, different inputs".
        previous_output = None

        # Render prompt from template
        full_prompt = render_classify_prompt(serialized, sorted_labels, previous_output, multi)

        # Create classification model for structured output
        ClassificationModel = create_classification_model(sorted_labels, multi)

        # Call LLM (with state tracking if enabled)
        doc_state = compile_ctx.doc_state if compile_ctx else None
        labels_display = ",".join(str(lbl) for lbl in sorted_labels[:3])
        if len(sorted_labels) > 3:
            labels_display += "..."
        op = doc_state.child("llm", detail=f"classify({labels_display})") if doc_state else None
        with op if op else _nullcontext():
            try:
                output_type: list[type] = [ClassificationModel]
                agent: Agent[None, Any] = Agent(  # type: ignore[assignment]
                    effective_model,
                    output_type=output_type,  # type: ignore[arg-type]
                )
                result = await agent.run(full_prompt)

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

                # Record LLM call for tracking
                if compile_ctx:
                    compile_ctx.add_llm_call(
                        LLMCall(
                            call_id=call_id,
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

    @cached(key="llm.complete")
    async def _complete(
        self,
        prompt: str,
        model: str | None = None,
    ) -> str:
        """Complete a prompt using LLM.

        Used for {% llm %}...{% endllm %} blocks.

        Args:
            prompt: The prompt to complete.
            model: Optional model override.

        Returns:
            The LLM response.
        """
        effective_model = infer_model(model or self.model or settings.default_llm_model)
        compile_ctx = get_compile_context()

        # Generate call_id for tracking
        call_id = f"llm.complete:{hash_args((prompt,), {})}"

        # TODO: previous_output should enable stability when inputs change,
        # but current auto-ID design ties cache key to input hash.
        # Needs redesign to support "same logical call, different inputs".
        previous_output = None

        # Render prompt from template
        full_prompt = render_complete_prompt(prompt, previous_output)

        # Call LLM (with state tracking if enabled)
        doc_state = compile_ctx.doc_state if compile_ctx else None
        op = doc_state.child("llm", detail=f"complete({_truncate(prompt)})") if doc_state else None
        with op if op else _nullcontext():
            try:
                output_type: list[type] = [str]
                agent: Agent[None, LLMOutput] = Agent(
                    effective_model,
                    output_type=output_type,  # type: ignore[arg-type]
                )
                result = await agent.run(full_prompt)
                output_text = str(result.output)

                # Record LLM call for tracking
                if compile_ctx:
                    compile_ctx.add_llm_call(
                        LLMCall(
                            call_id=call_id,
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
