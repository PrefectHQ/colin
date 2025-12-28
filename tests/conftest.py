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
    """
    with patch("colin.compiler.context.Agent") as mock_agent_class:
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

        yield mock_agent_class


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a minimal Colin project structure."""
    (tmp_path / "context").mkdir()
    (tmp_path / "sources").mkdir()
    (tmp_path / "skills").mkdir()
    (tmp_path / "dist").mkdir()
    (tmp_path / ".colin").mkdir()
    return tmp_path


@pytest.fixture
def sample_model_file(project_dir: Path) -> Path:
    """Create a sample model file."""
    path = project_dir / "context" / "sample.md"
    path.write_text("""\
---
colin:
  output: markdown
name: sample
description: A sample document
---

# Sample Document

This is sample content.
""")
    return path
