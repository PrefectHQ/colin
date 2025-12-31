"""Tests for Colin compiler context."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from colin.compiler import CompileContext
from colin.exceptions import RefNotFoundError
from colin.models import DocumentMeta, LLMCall, Manifest
from colin.providers.project import ProjectProvider
from colin.providers.storage.file import FileStorage


class TestCompileContext:
    @pytest.fixture
    def context(self, tmp_path: Path, mock_agent: MagicMock) -> CompileContext:
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

    async def test_ref_tracks_dependency(self, context: CompileContext, tmp_path: Path) -> None:
        source_file = tmp_path / "context" / "other.md"
        source_file.write_text("---\nname: Other\n---\nContent")
        output_file = tmp_path / "target" / "other.md"
        output_file.write_text("Compiled other")

        await context.ref("other")

        assert "project://other.md" in context.refs_evaluated

    async def test_ref_returns_ref_result(self, context: CompileContext, tmp_path: Path) -> None:
        source_file = tmp_path / "context" / "doc.md"
        source_file.write_text("---\nname: Doc\ndescription: A doc\n---\nTemplate")
        output_file = tmp_path / "target" / "doc.md"
        output_file.write_text("Compiled content")

        result = await context.ref("doc")

        # When reading from storage, name is derived from URI (not frontmatter)
        assert result.name == "doc.md"
        assert result.content == "Compiled content"
        assert str(result) == "Ref('project://doc.md')"

    async def test_ref_not_found(self, context: CompileContext) -> None:
        with pytest.raises(RefNotFoundError):
            await context.ref("nonexistent")

    async def test_extract_calls_llm(self, context: CompileContext, mock_agent: MagicMock) -> None:
        result = await context.extract("Some content", "Extract names")

        assert result is not None
        assert result == "[TEST LLM RESPONSE]"
        mock_agent.assert_called()

    async def test_extract_records_call(
        self, context: CompileContext, mock_agent: MagicMock
    ) -> None:
        await context.extract("Content", "Extract")

        assert len(context.llm_calls) == 1

    async def test_extract_with_manual_id(
        self, context: CompileContext, mock_agent: MagicMock
    ) -> None:
        await context.extract("Content", "Extract", call_id="my-id")

        assert "my-id" in context.llm_calls

    async def test_extract_auto_id_is_deterministic(
        self, context: CompileContext, mock_agent: MagicMock
    ) -> None:
        await context.extract("Content", "Extract")
        call_id = list(context.llm_calls.keys())[0]

        assert call_id.startswith("auto:")

    async def test_extract_caches_on_same_input(
        self, context: CompileContext, tmp_path: Path, mock_agent: MagicMock
    ) -> None:
        context.manifest.set_document(
            "test-doc",
            DocumentMeta(
                uri="test-doc",
                source_hash="abc",
                llm_calls={
                    "auto:1234567890123456": LLMCall(
                        call_id="auto:1234567890123456",
                        input_hash=context._hash("Content"),
                        output_hash="out",
                        output="Cached result",
                        model="test-model",
                    )
                },
            ),
        )

        result = await context.extract("Content", "Extract", call_id="auto:1234567890123456")
        assert result == "Cached result"

    async def test_call_llm_block(self, context: CompileContext, mock_agent: MagicMock) -> None:
        result = await context.call_llm_block(
            body="Test prompt",
            model=None,
            call_id=None,
        )

        assert result is not None
        assert result == "[TEST LLM RESPONSE]"

    async def test_call_llm_block_records_call(
        self, context: CompileContext, mock_agent: MagicMock
    ) -> None:
        await context.call_llm_block(
            body="Test prompt",
            model=None,
            call_id="block-1",
        )

        assert "block-1" in context.llm_calls

    async def test_classify_calls_llm(self, context: CompileContext, mock_agent: MagicMock) -> None:
        """Test that classify calls the LLM with structured output."""
        from colin.llm.types import create_classification_model

        # Create a mock classification model instance
        ClassificationModel = create_classification_model(["movie", "book", "podcast"], False)
        mock_classification = ClassificationModel(label="movie")

        # Update mock to return classification model
        mock_result = MagicMock()
        mock_result.output = mock_classification
        mock_result.usage.return_value = None

        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value=mock_result)
        mock_agent.return_value = mock_instance

        result = await context.classify("Some content about a film", ["movie", "book", "podcast"])

        assert result == "movie"
        mock_agent.assert_called()

    async def test_classify_records_call(
        self, context: CompileContext, mock_agent: MagicMock
    ) -> None:
        """Test that classify records the LLM call."""
        from colin.llm.types import create_classification_model

        ClassificationModel = create_classification_model(["positive", "negative"], False)
        mock_classification = ClassificationModel(label="positive")

        mock_result = MagicMock()
        mock_result.output = mock_classification
        mock_result.usage.return_value = None

        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value=mock_result)
        mock_agent.return_value = mock_instance

        await context.classify("Content", ["positive", "negative"])

        assert len(context.llm_calls) == 1

    async def test_classify_with_manual_id(
        self, context: CompileContext, mock_agent: MagicMock
    ) -> None:
        """Test classify with manual call ID."""
        from colin.llm.types import create_classification_model

        ClassificationModel = create_classification_model(["a", "b"], False)
        mock_classification = ClassificationModel(label="a")

        mock_result = MagicMock()
        mock_result.output = mock_classification
        mock_result.usage.return_value = None

        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value=mock_result)
        mock_agent.return_value = mock_instance

        await context.classify("Content", ["a", "b"], call_id="my-classify-id")

        assert "my-classify-id" in context.llm_calls

    async def test_classify_auto_id_is_deterministic(
        self, context: CompileContext, mock_agent: MagicMock
    ) -> None:
        """Test that classify generates deterministic auto IDs."""
        from colin.llm.types import create_classification_model

        ClassificationModel = create_classification_model(["x", "y"], False)
        mock_classification = ClassificationModel(label="x")

        mock_result = MagicMock()
        mock_result.output = mock_classification
        mock_result.usage.return_value = None

        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value=mock_result)
        mock_agent.return_value = mock_instance

        await context.classify("Content", ["x", "y"])
        call_id = list(context.llm_calls.keys())[0]

        assert call_id.startswith("auto:")

    async def test_classify_caches_on_same_input(
        self, context: CompileContext, tmp_path: Path, mock_agent: MagicMock
    ) -> None:
        """Test that classify uses cached results when input matches."""
        context.manifest.set_document(
            "test-doc",
            DocumentMeta(
                uri="test-doc",
                source_hash="abc",
                llm_calls={
                    "auto:1234567890123456": LLMCall(
                        call_id="auto:1234567890123456",
                        input_hash=context._hash("Content"),
                        output_hash="out",
                        output="movie",
                        model="test-model",
                    )
                },
            ),
        )

        result = await context.classify(
            "Content", ["movie", "book"], call_id="auto:1234567890123456"
        )
        assert result == "movie"

    async def test_classify_multi_label(
        self, context: CompileContext, mock_agent: MagicMock
    ) -> None:
        """Test multi-label classification."""
        from colin.llm.types import create_classification_model

        ClassificationModel = create_classification_model(["tag1", "tag2", "tag3"], True)
        mock_classification = ClassificationModel(labels=["tag1", "tag2"])

        mock_result = MagicMock()
        mock_result.output = mock_classification
        mock_result.usage.return_value = None

        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value=mock_result)
        mock_agent.return_value = mock_instance

        result = await context.classify("Content", ["tag1", "tag2", "tag3"], multi=True)

        assert isinstance(result, list)
        assert result == ["tag1", "tag2"]

    async def test_classify_empty_labels_raises_error(
        self, context: CompileContext, mock_agent: MagicMock
    ) -> None:
        """Test that classify raises error with empty labels."""
        with pytest.raises(ValueError, match="Labels list cannot be empty"):
            await context.classify("Content", [])
