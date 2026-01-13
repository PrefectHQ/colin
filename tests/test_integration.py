"""Integration tests using fixture files."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from colin.api.project import ProjectConfig, ProjectOutputConfig
from colin.compiler import CompileEngine
from colin.providers.storage.file import FileStorage


class TestCompileIntegration:
    """Integration tests that compile real fixture files."""

    @pytest.fixture(autouse=True)
    def setup_mock(self, mock_agent: MagicMock) -> None:
        """Ensure mock_agent is active for all tests."""
        pass

    async def test_hello_world_example(self, tmp_path: Path) -> None:
        """Test compiling the hello_world example end-to-end."""
        # Set up directories
        source_dir = tmp_path / "models"
        source_dir.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir(parents=True)
        build_dir = tmp_path / ".colin"
        build_dir.mkdir()
        compiled_dir = build_dir / "compiled"
        compiled_dir.mkdir()

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

{{ ref('greeting.md').content }}

---

You just saw an example of `ref()` pulling in content from another document.
""")

        (source_dir / "summary.md").write_text("""\
---
name: Summary
description: Demonstrates LLM blocks and llm_extract filter
---

# Summary Example

Here's some content to work with:

{{ ref('greeting.md').content }}

## Extracted Info

{{ ref('greeting.md') | llm_extract('the main message in one sentence') }}

## LLM-Generated Content

{% llm %}
Given this greeting:
{{ ref('greeting.md').content }}

Write a haiku about being welcomed.
{% endllm %}
""")

        # Compile
        config = ProjectConfig(
            name="test-project",
            project_root=tmp_path,
            model_path=source_dir,
            output_path=tmp_path / "output",
            manifest_path=tmp_path / ".colin" / "manifest.json",
        )
        artifact_storage = FileStorage(base_path=compiled_dir)
        engine = CompileEngine(
            config=config,
            artifact_storage=artifact_storage,
        )

        compiled = await engine.compile_all()

        # Verify compile order (greeting must be first)
        uris = [doc.uri for doc in compiled]
        assert uris.index("project://greeting.md") < uris.index("project://welcome.md")
        assert uris.index("project://greeting.md") < uris.index("project://summary.md")

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
        summary_doc = next(d for d in compiled if d.uri == "project://summary.md")
        assert len(summary_doc.llm_calls) == 2  # extract + llm block

        # Verify test LLM responses
        assert "[TEST LLM RESPONSE]" in summary_output

    async def test_diamond_dependency(self, tmp_path: Path) -> None:
        """Test diamond dependency pattern (A depends on B and C, both depend on D)."""
        source_dir = tmp_path / "models"
        source_dir.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir(parents=True)
        build_dir = tmp_path / ".colin"
        build_dir.mkdir()
        compiled_dir = build_dir / "compiled"
        compiled_dir.mkdir()

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
B uses {{ ref('d.md').content }}
""")

        # C depends on D
        (source_dir / "c.md").write_text("""\
---
name: C
---
C uses {{ ref('d.md').content }}
""")

        # A depends on B and C
        (source_dir / "a.md").write_text("""\
---
name: A
---
A uses {{ ref('b.md').content }} and {{ ref('c.md').content }}
""")

        # Compile
        config = ProjectConfig(
            name="test-project",
            project_root=tmp_path,
            model_path=source_dir,
            output_path=tmp_path / "output",
            manifest_path=tmp_path / ".colin" / "manifest.json",
        )
        artifact_storage = FileStorage(base_path=compiled_dir)
        engine = CompileEngine(
            config=config,
            artifact_storage=artifact_storage,
        )

        compiled = await engine.compile_all()

        # Verify order: D must be first, A must be last
        uris = [doc.uri for doc in compiled]
        assert uris.index("project://d.md") < uris.index("project://b.md")
        assert uris.index("project://d.md") < uris.index("project://c.md")
        assert uris.index("project://b.md") < uris.index("project://a.md")
        assert uris.index("project://c.md") < uris.index("project://a.md")

        # Verify content propagation
        a_output = (output_dir / "a.md").read_text()
        assert "D content" in a_output

    async def test_nested_directories(self, tmp_path: Path) -> None:
        """Test documents in nested directories."""
        source_dir = tmp_path / "models"
        source_dir.mkdir()
        (source_dir / "reports").mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir(parents=True)
        build_dir = tmp_path / ".colin"
        build_dir.mkdir()
        compiled_dir = build_dir / "compiled"
        compiled_dir.mkdir()

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
Report includes {{ ref('base.md').content }}
""")

        # Compile
        config = ProjectConfig(
            name="test-project",
            project_root=tmp_path,
            model_path=source_dir,
            output_path=tmp_path / "output",
            manifest_path=tmp_path / ".colin" / "manifest.json",
        )
        artifact_storage = FileStorage(base_path=compiled_dir)
        engine = CompileEngine(
            config=config,
            artifact_storage=artifact_storage,
        )

        await engine.compile_all()

        # Verify nested output
        assert (output_dir / "reports" / "weekly.md").exists()
        weekly_output = (output_dir / "reports" / "weekly.md").read_text()
        assert "Base content" in weekly_output

    async def test_output_manifest_default(self, tmp_path: Path) -> None:
        """Test that output manifest is written with default plugin."""
        source_dir = tmp_path / "models"
        source_dir.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir(parents=True)
        build_dir = tmp_path / ".colin"
        build_dir.mkdir()
        compiled_dir = build_dir / "compiled"
        compiled_dir.mkdir()

        # Create colin.toml for project ID
        (tmp_path / "colin.toml").write_text("""\
[project]
name = "test-project"
id = "test-project-abc123"
""")

        (source_dir / "hello.md").write_text("""\
---
name: Hello
---
Hello World
""")

        config = ProjectConfig(
            name="test-project",
            id="test-project-abc123",
            project_root=tmp_path,
            model_path=source_dir,
            output_path=output_dir,
            manifest_path=tmp_path / ".colin" / "manifest.json",
        )
        artifact_storage = FileStorage(base_path=compiled_dir)
        engine = CompileEngine(
            config=config,
            artifact_storage=artifact_storage,
        )

        await engine.compile_all()

        # Verify output manifest exists at root
        manifest_path = output_dir / ".colin-manifest.json"
        assert manifest_path.exists()

        manifest = json.loads(manifest_path.read_text())
        assert manifest["project_id"] == "test-project-abc123"
        assert "hello.md" in manifest["files"]

    async def test_output_manifest_skill_target(self, tmp_path: Path) -> None:
        """Test that skill target writes per-subdirectory manifests."""
        source_dir = tmp_path / "models"
        source_dir.mkdir()
        output_dir = tmp_path / "output" / "skills"
        output_dir.mkdir(parents=True)
        build_dir = tmp_path / ".colin"
        build_dir.mkdir()
        compiled_dir = build_dir / "compiled"
        compiled_dir.mkdir()

        # Create colin.toml for project ID
        (tmp_path / "colin.toml").write_text("""\
[project]
name = "test-skills"
id = "test-skills-xyz789"

[project.output]
target = "skill"
path = "output/skills"
""")

        # Create skill files with subdirectory structure
        (source_dir / "stripe.md").write_text("""\
---
colin:
  output:
    path: stripe/SKILL.md
---
Stripe skill
""")

        (source_dir / "github.md").write_text("""\
---
colin:
  output:
    path: github/SKILL.md
---
GitHub skill
""")

        config = ProjectConfig(
            name="test-skills",
            id="test-skills-xyz789",
            project_root=tmp_path,
            model_path=source_dir,
            output_path=output_dir,
            manifest_path=tmp_path / ".colin" / "manifest.json",
            output=ProjectOutputConfig(target="skill", path="output/skills"),
        )
        artifact_storage = FileStorage(base_path=compiled_dir)
        engine = CompileEngine(
            config=config,
            artifact_storage=artifact_storage,
        )

        await engine.compile_all()

        # Verify per-subdirectory manifests
        stripe_manifest = output_dir / "stripe" / ".colin-manifest.json"
        github_manifest = output_dir / "github" / ".colin-manifest.json"

        assert stripe_manifest.exists()
        assert github_manifest.exists()

        stripe_data = json.loads(stripe_manifest.read_text())
        assert stripe_data["project_id"] == "test-skills-xyz789"
        assert "SKILL.md" in stripe_data["files"]

        github_data = json.loads(github_manifest.read_text())
        assert github_data["project_id"] == "test-skills-xyz789"
        assert "SKILL.md" in github_data["files"]

    async def test_output_manifest_ephemeral_skips(self, tmp_path: Path) -> None:
        """Test that ephemeral mode skips manifest writing."""
        source_dir = tmp_path / "models"
        source_dir.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir(parents=True)
        build_dir = tmp_path / ".colin"
        build_dir.mkdir()
        compiled_dir = build_dir / "compiled"
        compiled_dir.mkdir()

        (tmp_path / "colin.toml").write_text("""\
[project]
name = "test-project"
id = "test-project-abc123"
""")

        (source_dir / "hello.md").write_text("""\
---
name: Hello
---
Hello World
""")

        config = ProjectConfig(
            name="test-project",
            id="test-project-abc123",
            project_root=tmp_path,
            model_path=source_dir,
            output_path=output_dir,
            manifest_path=tmp_path / ".colin" / "manifest.json",
        )
        artifact_storage = FileStorage(base_path=compiled_dir)
        engine = CompileEngine(
            config=config,
            artifact_storage=artifact_storage,
            ephemeral=True,
        )

        await engine.compile_all()

        # Verify NO output manifest in ephemeral mode
        manifest_path = output_dir / ".colin-manifest.json"
        assert not manifest_path.exists()
