"""Integration tests using fixture files."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from colin.compiler import CompileEngine
from colin.models import Manifest
from colin.plugins.inputs.file import FileInputPlugin

if TYPE_CHECKING:
    pass


class TestCompileIntegration:
    """Integration tests that compile real fixture files."""

    @pytest.fixture(autouse=True)
    def setup_mock(self, mock_agent: MagicMock) -> None:
        """Ensure mock_agent is active for all tests."""
        pass

    async def test_hello_world_example(self, tmp_path: Path) -> None:
        """Test compiling the hello_world example end-to-end."""
        # Set up directories
        source_dir = tmp_path / "context"
        source_dir.mkdir()
        output_dir = tmp_path / "target"

        # Create fixture files (same as examples/hello_world)
        (source_dir / "greeting.md").write_text("""\
---
name: Greeting
description: A friendly greeting message
---

Hello! Welcome to Colin.

This is a simple document that other documents can reference.
""")

        (source_dir / "welcome.md").write_text("""\
---
name: Welcome Message
description: Demonstrates ref() to include other documents
---

# Welcome

{{ ref('greeting').content }}

---

You just saw an example of `ref()` pulling in content from another document.
""")

        (source_dir / "summary.md").write_text("""\
---
name: Summary
description: Demonstrates LLM blocks and extract filter
---

# Summary Example

Here's some content to work with:

{{ ref('greeting').content }}

## Extracted Info

{{ ref('greeting') | extract('the main message in one sentence') }}

## LLM-Generated Content

{% llm %}
Given this greeting:
{{ ref('greeting').content }}

Write a haiku about being welcomed.
{% endllm %}
""")

        # Compile
        input_plugin = FileInputPlugin([source_dir], target_dir=output_dir)
        manifest = Manifest()
        engine = CompileEngine(manifest, input_plugin, default_model="test-model")

        compiled = await engine.compile_all()

        # Verify compile order (greeting must be first)
        uris = [doc.uri for doc in compiled]
        assert uris.index("greeting") < uris.index("welcome")
        assert uris.index("greeting") < uris.index("summary")

        # Verify output files exist
        assert (output_dir / "greeting.md").exists()
        assert (output_dir / "welcome.md").exists()
        assert (output_dir / "summary.md").exists()

        # Verify greeting content appears in welcome
        welcome_output = (output_dir / "welcome.md").read_text()
        assert "Hello! Welcome to Colin." in welcome_output

        # Verify greeting content appears in summary
        summary_output = (output_dir / "summary.md").read_text()
        assert "Hello! Welcome to Colin." in summary_output

        # Verify LLM calls were made for summary
        summary_doc = next(d for d in compiled if d.uri == "summary")
        assert len(summary_doc.llm_calls) == 2  # extract + llm block

        # Verify test LLM responses
        assert "[TEST LLM RESPONSE]" in summary_output

    async def test_diamond_dependency(self, tmp_path: Path) -> None:
        """Test diamond dependency pattern (A depends on B and C, both depend on D)."""
        source_dir = tmp_path / "context"
        source_dir.mkdir()
        output_dir = tmp_path / "target"

        # D is the base (no deps)
        (source_dir / "d.md").write_text("""\
---
name: D
---
D content
""")

        # B depends on D
        (source_dir / "b.md").write_text("""\
---
name: B
---
B uses {{ ref('d').content }}
""")

        # C depends on D
        (source_dir / "c.md").write_text("""\
---
name: C
---
C uses {{ ref('d').content }}
""")

        # A depends on B and C
        (source_dir / "a.md").write_text("""\
---
name: A
---
A uses {{ ref('b').content }} and {{ ref('c').content }}
""")

        # Compile
        input_plugin = FileInputPlugin([source_dir], target_dir=output_dir)
        manifest = Manifest()
        engine = CompileEngine(manifest, input_plugin, default_model="test-model")

        compiled = await engine.compile_all()

        # Verify order: D must be first, A must be last
        uris = [doc.uri for doc in compiled]
        assert uris.index("d") < uris.index("b")
        assert uris.index("d") < uris.index("c")
        assert uris.index("b") < uris.index("a")
        assert uris.index("c") < uris.index("a")

        # Verify content propagation
        a_output = (output_dir / "a.md").read_text()
        assert "D content" in a_output

    async def test_nested_directories(self, tmp_path: Path) -> None:
        """Test documents in nested directories."""
        source_dir = tmp_path / "context"
        source_dir.mkdir()
        (source_dir / "reports").mkdir()
        output_dir = tmp_path / "target"

        (source_dir / "base.md").write_text("""\
---
name: Base
---
Base content
""")

        (source_dir / "reports" / "weekly.md").write_text("""\
---
name: Weekly Report
---
Report includes {{ ref('base').content }}
""")

        # Compile
        input_plugin = FileInputPlugin([source_dir], target_dir=output_dir)
        manifest = Manifest()
        engine = CompileEngine(manifest, input_plugin, default_model="test-model")

        await engine.compile_all()

        # Verify nested output
        assert (output_dir / "reports" / "weekly.md").exists()
        weekly_output = (output_dir / "reports" / "weekly.md").read_text()
        assert "Base content" in weekly_output
