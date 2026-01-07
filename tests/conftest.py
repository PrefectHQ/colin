"""Pytest configuration and fixtures for Colin tests."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture
def mock_agent() -> Generator[MagicMock, None, None]:
    """Mock pydantic_ai.Agent for testing.

    Returns a mock that simulates Agent behavior with predictable outputs.
    Also mocks infer_model to accept any model string.
    """
    with (
        patch("colin.providers.llm.Agent") as mock_agent_class,
        patch("colin.providers.llm.infer_model") as mock_infer_model,
    ):
        # Create a mock agent instance
        mock_instance = MagicMock()

        # Create a mock result with .output attribute
        mock_result = MagicMock()
        mock_result.output = "[TEST LLM RESPONSE]"
        mock_result.usage.return_value = None

        # Make run() return the mock result
        mock_instance.run = AsyncMock(return_value=mock_result)

        # Make the class return the mock instance
        mock_agent_class.return_value = mock_instance

        # Mock infer_model to return a mock model with model_name attribute
        mock_model = MagicMock()
        mock_model.model_name = "test-model"
        mock_infer_model.return_value = mock_model

        yield mock_agent_class


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a minimal Colin project structure."""
    (tmp_path / "context").mkdir()
    (tmp_path / "sources").mkdir()
    (tmp_path / "skills").mkdir()
    (tmp_path / "dist").mkdir()
    (tmp_path / ".colin").mkdir()
    (tmp_path / ".colin" / "compiled").mkdir()
    return tmp_path


@pytest.fixture
def sample_model_file(project_dir: Path) -> Path:
    """Create a sample model file."""
    path = project_dir / "context" / "sample.md"
    path.write_text("""\
---
colin:
  output:
    format: markdown
name: sample
description: A sample document
---

# Sample Document

This is sample content.
""")
    return path
