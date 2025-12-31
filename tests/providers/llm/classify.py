"""Tests for classify functionality with TestModel and FunctionModel."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic_ai import Agent, ModelMessage, ModelResponse, TextPart, models
from pydantic_ai.models.function import FunctionModel

from colin.compiler import CompileContext
from colin.llm.types import UseExisting, create_classification_model
from colin.models import DocumentMeta, LLMCall, Manifest
from colin.providers.project import ProjectProvider
from colin.providers.storage.file import FileStorage

# Block real API requests during tests
models.ALLOW_MODEL_REQUESTS = False  # type: ignore[assignment]


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


def create_classify_function_model(label: str | bool, labels: list[str | bool]) -> FunctionModel:
    """Create a FunctionModel that returns a specific label."""

    def classify_function(messages: list[ModelMessage], info) -> ModelResponse:  # type: ignore[no-untyped-def]
        """Function that returns a classification result."""
        # Create the classification model and return it as JSON
        ClassificationModel = create_classification_model(labels, False)
        classification = ClassificationModel(label=label)  # type: ignore[arg-type]
        # Return as JSON that pydantic_ai will parse into the ClassificationModel
        return ModelResponse(parts=[TextPart(content=classification.model_dump_json())])

    return FunctionModel(classify_function)


def create_multi_classify_function_model(
    labels: list[str], selected_labels: list[str]
) -> FunctionModel:
    """Create a FunctionModel that returns multiple labels."""

    def classify_function(messages: list[ModelMessage], info) -> ModelResponse:  # type: ignore[no-untyped-def]
        """Function that returns a multi-label classification result."""
        ClassificationModel = create_classification_model(labels, True)  # type: ignore[arg-type]
        classification = ClassificationModel(labels=selected_labels)
        # Return JSON that pydantic_ai will parse
        return ModelResponse(parts=[TextPart(content=classification.model_dump_json())])

    return FunctionModel(classify_function)


def create_classify_agent_factory(label: str | bool, labels: list[str | bool]):
    """Create an agent factory using FunctionModel for classification."""

    def agent_factory(*args, **kwargs):
        """Factory that creates Agent with FunctionModel, ignoring model string."""
        function_model = create_classify_function_model(label, labels)
        ClassificationModel = create_classification_model(labels, False)
        # Use output_type from kwargs (Agent is called with output_type=...)
        output_type = kwargs.get("output_type", ClassificationModel)
        return Agent(function_model, output_type=output_type)

    return agent_factory


def create_multi_classify_agent_factory(labels: list[str], selected_labels: list[str]):
    """Create an agent factory using FunctionModel for multi-label classification."""

    def agent_factory(*args, **kwargs):
        """Factory that creates Agent with FunctionModel, ignoring model string."""
        function_model = create_multi_classify_function_model(labels, selected_labels)
        ClassificationModel = create_classification_model(labels, True)  # type: ignore[arg-type]
        # Use output_type from kwargs (Agent is called with output_type=...)
        output_type = kwargs.get("output_type", ClassificationModel)
        return Agent(function_model, output_type=output_type)

    return agent_factory


async def test_classify_calls_llm(context: CompileContext) -> None:
    """Test that classify calls the LLM and returns a label."""
    labels = ["positive", "negative", "neutral"]
    agent_factory = create_classify_agent_factory("positive", labels)

    with patch("colin.compiler.context.Agent", side_effect=agent_factory):
        result = await context.classify("Great product!", labels)

        assert result == "positive"


async def test_classify_records_call(context: CompileContext) -> None:
    """Test that classify records the LLM call."""
    labels = ["a", "b"]
    agent_factory = create_classify_agent_factory("a", labels)

    with patch("colin.compiler.context.Agent", side_effect=agent_factory):
        await context.classify("Content", labels)

        assert len(context.llm_calls) == 1
        call_id = list(context.llm_calls.keys())[0]
        assert call_id.startswith("auto:")


async def test_classify_with_manual_id(context: CompileContext) -> None:
    """Test classify with manual call ID."""
    labels = ["a", "b"]
    agent_factory = create_classify_agent_factory("a", labels)

    with patch("colin.compiler.context.Agent", side_effect=agent_factory):
        await context.classify("Content", labels, call_id="my-classify-id")

        assert "my-classify-id" in context.llm_calls
        call = context.llm_calls["my-classify-id"]
        assert call.call_id == "my-classify-id"


async def test_classify_auto_id_is_deterministic(context: CompileContext) -> None:
    """Test that auto-generated call IDs are deterministic."""
    labels = ["x", "y"]
    agent_factory = create_classify_agent_factory("x", labels)

    with patch("colin.compiler.context.Agent", side_effect=agent_factory):
        await context.classify("Content", labels)
        call_id1 = list(context.llm_calls.keys())[0]

        # Clear calls and call again with same input
        context.llm_calls.clear()
        await context.classify("Content", labels)
        call_id2 = list(context.llm_calls.keys())[0]

        assert call_id1 == call_id2


async def test_classify_caches_on_same_input(context: CompileContext, tmp_path: Path) -> None:
    """Test that classify uses cached results when input matches."""
    content = "Content"
    labels = ["movie", "book"]
    call_id = "auto:1234567890123456"
    cached_output = "movie"

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

    # Classify should return cached result without calling LLM
    with patch("colin.compiler.context.Agent") as mock_agent_class:
        result = await context.classify(content, labels, call_id=call_id)

        assert result == cached_output
        assert len(context.llm_calls) == 0
        mock_agent_class.assert_not_called()


async def test_classify_cache_busting_on_different_input(context: CompileContext) -> None:
    """Test that classify bypasses cache when input changes."""
    call_id = "manual-id"
    original_content = "Original content"
    new_content = "Different content"
    labels = ["a", "b"]
    agent_factory = create_classify_agent_factory("a", labels)

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
                    output="a",
                    model="test-model",
                )
            },
        ),
    )

    # Classify with different content should call LLM
    with patch("colin.compiler.context.Agent", side_effect=agent_factory) as mock_agent_class:
        result = await context.classify(new_content, labels, call_id=call_id)

        assert result == "a"
        assert len(context.llm_calls) == 1
        mock_agent_class.assert_called()


async def test_classify_multi_label(context: CompileContext) -> None:
    """Test multi-label classification."""
    labels = ["tag1", "tag2", "tag3"]
    expected_labels = ["tag1", "tag2"]
    agent_factory = create_multi_classify_agent_factory(labels, expected_labels)

    with patch("colin.compiler.context.Agent", side_effect=agent_factory):
        result = await context.classify("Content", labels, multi=True)

        assert isinstance(result, list)
        assert result == expected_labels


async def test_classify_with_bool_labels(context: CompileContext) -> None:
    """Test classification with boolean labels."""
    labels: list[str | bool] = [True, False]
    agent_factory = create_classify_agent_factory(True, labels)

    with patch("colin.compiler.context.Agent", side_effect=agent_factory):
        result = await context.classify("Content", labels)

        assert result is True


async def test_classify_with_mixed_labels(context: CompileContext) -> None:
    """Test classification with mixed string and bool labels."""
    labels: list[str | bool] = ["yes", "no", True, False]
    agent_factory = create_classify_agent_factory("yes", labels)

    with patch("colin.compiler.context.Agent", side_effect=agent_factory):
        result = await context.classify("Content", labels)

        assert result == "yes"


async def test_classify_empty_labels_raises_error(context: CompileContext) -> None:
    """Test that classify raises error with empty labels."""
    with pytest.raises(ValueError, match="Labels list cannot be empty"):
        await context.classify("Content", [])


async def test_classify_different_labels_different_ids(context: CompileContext) -> None:
    """Test that different label sets generate different auto IDs."""
    agent_factory1 = create_classify_agent_factory("a", ["a", "b"])
    agent_factory2 = create_classify_agent_factory("x", ["x", "y"])

    with patch("colin.compiler.context.Agent") as mock_agent_class:
        mock_agent_class.side_effect = agent_factory1
        await context.classify("Content", ["a", "b"])
        call_id1 = list(context.llm_calls.keys())[0]

        mock_agent_class.side_effect = agent_factory2
        await context.classify("Content", ["x", "y"])
        call_id2 = list(context.llm_calls.keys())[1]

        assert call_id1 != call_id2


async def test_classify_multi_vs_single_different_ids(context: CompileContext) -> None:
    """Test that multi=True generates different ID than multi=False."""
    labels = ["a", "b"]
    agent_factory1 = create_classify_agent_factory("a", labels)
    agent_factory2 = create_multi_classify_agent_factory(labels, ["a"])

    with patch("colin.compiler.context.Agent") as mock_agent_class:
        mock_agent_class.side_effect = agent_factory1
        await context.classify("Content", labels, multi=False)
        call_id1 = list(context.llm_calls.keys())[0]

        context.llm_calls.clear()
        mock_agent_class.side_effect = agent_factory2
        await context.classify("Content", labels, multi=True)
        call_id2 = list(context.llm_calls.keys())[0]

        # Should generate different IDs because multi flag is different
        assert call_id1 != call_id2


async def test_classify_with_model_override(context: CompileContext) -> None:
    """Test that classify respects model override."""
    labels = ["a", "b"]
    agent_factory = create_classify_agent_factory("a", labels)

    with patch("colin.compiler.context.Agent", side_effect=agent_factory) as mock_agent_class:
        await context.classify("Content", labels, model="custom-model")

        mock_agent_class.assert_called()
        # Verify it was called with the custom model (first arg)
        call_args = mock_agent_class.call_args
        assert call_args[0][0] == "custom-model"


async def test_classify_uses_previous_output_for_stability(context: CompileContext) -> None:
    """Test that classify uses previous output when call_id is provided."""
    call_id = "stable-id"
    previous_output = "positive"
    labels = ["positive", "negative"]

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
    def use_existing_function(messages: list[ModelMessage], info) -> ModelResponse:  # type: ignore[no-untyped-def]
        """Function that returns UseExisting."""
        return ModelResponse(parts=[TextPart(content=UseExisting().model_dump_json())])

    def use_existing_factory(*args, **kwargs):
        """Factory that creates Agent returning UseExisting."""
        use_existing_model = FunctionModel(use_existing_function)
        ClassificationModel = create_classification_model(labels, False)
        output_type = kwargs.get("output_type") or [UseExisting, ClassificationModel]
        return Agent(use_existing_model, output_type=output_type)

    with patch("colin.compiler.context.Agent", side_effect=use_existing_factory):
        result = await context.classify("Content", labels, call_id=call_id)

        # Should return previous output when UseExisting is returned
        assert result == previous_output


async def test_classify_sorted_labels_for_consistency(context: CompileContext) -> None:
    """Test that labels are sorted for consistent hashing."""
    labels1 = ["b", "a", "c"]
    labels2 = ["a", "b", "c"]
    agent_factory = create_classify_agent_factory("a", labels1)

    with patch("colin.compiler.context.Agent", side_effect=agent_factory):
        await context.classify("Content", labels1)
        call_id1 = list(context.llm_calls.keys())[0]

        context.llm_calls.clear()
        await context.classify("Content", labels2)
        call_id2 = list(context.llm_calls.keys())[0]

        # Should generate same ID despite different label order
        assert call_id1 == call_id2
