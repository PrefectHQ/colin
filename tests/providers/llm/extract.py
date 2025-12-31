"""Tests for extract functionality with TestModel."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic_ai import Agent, models
from pydantic_ai.models.test import TestModel

from colin.compiler import CompileContext
from colin.llm.types import UseExisting
from colin.models import DocumentMeta, LLMCall, Manifest
from colin.providers.project import ProjectProvider
from colin.providers.storage.file import FileStorage

# Block real API requests during tests
models.ALLOW_MODEL_REQUESTS = False


@pytest.fixture
def context(tmp_path: Path) -> CompileContext:
    """Create a CompileContext for testing."""
    source_dir = tmp_path / "context"
    source_dir.mkdir()
    output_dir = tmp_path / "target"
    output_dir.mkdir()

    manifest = Manifest()
    file_storage = FileStorage(base_path=output_dir)
    project_provider = ProjectProvider(storage=file_storage)

    return CompileContext(
        manifest=manifest,
        document_uri="test-doc",
        default_model="test-model",
        project_provider=project_provider,
    )


@pytest.fixture
def test_model() -> TestModel:
    """Create a TestModel instance."""
    return TestModel(custom_output_text="Extracted content")


def create_test_agent_factory(output_text: str = "Extracted content"):
    """Create a function that returns an Agent instance using TestModel."""

    def agent_factory(*args, **kwargs):
        """Factory that creates Agent with TestModel, ignoring model string."""
        # Extract output_type from kwargs (Agent is called with output_type=...)
        output_type = kwargs.get("output_type", str)
        return Agent(TestModel(custom_output_text=output_text), output_type=output_type)

    return agent_factory


async def test_extract_calls_llm(context: CompileContext, test_model: TestModel) -> None:
    """Test that extract calls the LLM and returns a response."""
    agent_factory = create_test_agent_factory("Extracted: names")

    with patch("colin.compiler.context.Agent", side_effect=agent_factory):
        result = await context.extract("Some content", "Extract names")

        assert result is not None
        assert isinstance(result, str)
        assert result == "Extracted: names"


async def test_extract_records_call(context: CompileContext, test_model: TestModel) -> None:
    """Test that extract records the LLM call in context."""
    agent_factory = create_test_agent_factory("Extracted content")

    with patch("colin.compiler.context.Agent", side_effect=agent_factory):
        await context.extract("Content", "Extract")

        assert len(context.llm_calls) == 1
        call_id = list(context.llm_calls.keys())[0]
        assert call_id.startswith("auto:")


async def test_extract_with_manual_id(context: CompileContext, test_model: TestModel) -> None:
    """Test extract with manual call ID for caching."""
    agent_factory = create_test_agent_factory("Extracted")

    with patch("colin.compiler.context.Agent", side_effect=agent_factory):
        await context.extract("Content", "Extract", call_id="my-id")

        assert "my-id" in context.llm_calls
        call = context.llm_calls["my-id"]
        assert call.call_id == "my-id"
        assert call.model == "test-model"


async def test_extract_auto_id_is_deterministic(
    context: CompileContext, test_model: TestModel
) -> None:
    """Test that auto-generated call IDs are deterministic."""
    agent_factory = create_test_agent_factory("Extracted")

    with patch("colin.compiler.context.Agent", side_effect=agent_factory):
        await context.extract("Content", "Extract")
        call_id1 = list(context.llm_calls.keys())[0]

        # Clear calls and call again with same input
        context.llm_calls.clear()
        await context.extract("Content", "Extract")
        call_id2 = list(context.llm_calls.keys())[0]

        assert call_id1 == call_id2
        assert call_id1.startswith("auto:")


async def test_extract_caches_on_same_input(
    context: CompileContext, tmp_path: Path, test_model: TestModel
) -> None:
    """Test that extract uses cached results when input matches."""
    content = "Content"
    call_id = "auto:1234567890123456"
    cached_output = "Cached result"

    # Set up cached call in manifest
    context.manifest.set_document(
        "test-doc",
        DocumentMeta(
            uri="test-doc",
            source_hash="abc",
            llm_calls={
                call_id: LLMCall(
                    call_id=call_id,
                    input_hash=context._hash(content),
                    output_hash="out",
                    output=cached_output,
                    model="test-model",
                )
            },
        ),
    )

    # Extract should return cached result without calling LLM
    with patch("colin.compiler.context.Agent") as mock_agent_class:
        result = await context.extract(content, "Extract", call_id=call_id)

        # Should return cached result
        assert result == cached_output
        # Should not create new call
        assert len(context.llm_calls) == 0
        # Agent should not be called
        mock_agent_class.assert_not_called()


async def test_extract_cache_busting_on_different_input(
    context: CompileContext, test_model: TestModel
) -> None:
    """Test that extract bypasses cache when input changes."""
    call_id = "manual-id"
    original_content = "Original content"
    new_content = "Different content"

    # Set up cached call with original content
    context.manifest.set_document(
        "test-doc",
        DocumentMeta(
            uri="test-doc",
            source_hash="abc",
            llm_calls={
                call_id: LLMCall(
                    call_id=call_id,
                    input_hash=context._hash(original_content),
                    output_hash="out",
                    output="Cached result",
                    model="test-model",
                )
            },
        ),
    )

    # Extract with different content should call LLM
    agent_factory = create_test_agent_factory("New result")
    with patch("colin.compiler.context.Agent", side_effect=agent_factory) as mock_agent_class:
        result = await context.extract(new_content, "Extract", call_id=call_id)

        # Should get new result
        assert result == "New result"
        # Should create new call
        assert len(context.llm_calls) == 1
        # Agent should be called
        mock_agent_class.assert_called()


async def test_extract_with_model_override(context: CompileContext, test_model: TestModel) -> None:
    """Test that extract respects model override."""
    agent_factory = create_test_agent_factory("Extracted")

    with patch("colin.compiler.context.Agent", side_effect=agent_factory) as mock_agent_class:
        await context.extract("Content", "Extract", model="custom-model")

        # Check that Agent was called with custom model
        mock_agent_class.assert_called()
        # Verify it was called with the custom model (first arg)
        call_args = mock_agent_class.call_args
        assert call_args[0][0] == "custom-model"


async def test_extract_uses_previous_output_for_stability(
    context: CompileContext, test_model: TestModel
) -> None:
    """Test that extract uses previous output when call_id is provided."""
    call_id = "stable-id"
    previous_output = "Previous extraction result"

    # Set up previous output in manifest
    context.manifest.set_document(
        "test-doc",
        DocumentMeta(
            uri="test-doc",
            source_hash="abc",
            llm_calls={
                call_id: LLMCall(
                    call_id=call_id,
                    input_hash=context._hash("Content"),
                    output_hash="out",
                    output=previous_output,
                    model="test-model",
                )
            },
        ),
    )

    # Create an agent factory that returns UseExisting
    def use_existing_factory(*args, **kwargs):
        """Factory that creates Agent returning UseExisting."""
        output_type = kwargs.get("output_type") or (
            args[1] if len(args) > 1 else [UseExisting, str]
        )
        return Agent(TestModel(), output_type=output_type)

    with patch("colin.compiler.context.Agent", side_effect=use_existing_factory):
        result = await context.extract("Content", "Extract", call_id=call_id)

        # Should return previous output when UseExisting is returned
        assert result == previous_output


async def test_extract_different_prompts_different_ids(
    context: CompileContext, test_model: TestModel
) -> None:
    """Test that different prompts generate different auto IDs."""
    agent_factory = create_test_agent_factory("Extracted")

    with patch("colin.compiler.context.Agent", side_effect=agent_factory):
        await context.extract("Content", "Prompt 1")
        call_id1 = list(context.llm_calls.keys())[0]

        await context.extract("Content", "Prompt 2")
        call_id2 = list(context.llm_calls.keys())[1]

        assert call_id1 != call_id2


async def test_extract_same_content_different_prompts(
    context: CompileContext, test_model: TestModel
) -> None:
    """Test that same content with different prompts creates separate calls."""
    content = "Same content"
    agent_factory = create_test_agent_factory("Extracted")

    with patch("colin.compiler.context.Agent", side_effect=agent_factory):
        await context.extract(content, "Prompt 1")
        await context.extract(content, "Prompt 2")

        assert len(context.llm_calls) == 2
