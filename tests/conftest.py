"""Pytest configuration and fixtures for Colin tests."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    pass


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
