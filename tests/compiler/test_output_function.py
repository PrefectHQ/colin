"""Tests for the output() template function."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from colin.api.compile import _save_manifest
from colin.api.project import ProjectConfig
from colin.compiler import CompileEngine
from colin.providers.storage.file import FileStorage


@pytest.fixture
def output_project(tmp_path: Path):
    """Create a test project for output() function tests."""
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    build_dir = tmp_path / ".colin"
    build_dir.mkdir()
    compiled_dir = build_dir / "compiled"
    compiled_dir.mkdir()
    output_dir = tmp_path / "output"

    config = ProjectConfig(
        name="output-test",
        project_root=tmp_path,
        model_path=models_dir,
        output_path=output_dir,
        manifest_path=build_dir / "manifest.json",
    )
    artifact_storage = FileStorage(base_path=compiled_dir)
    engine = CompileEngine(config=config, artifact_storage=artifact_storage)

    class ProjectHelper:
        def __init__(self, engine, config, tmp_path):
            self.engine = engine
            self.config = config
            self.tmp_path = tmp_path
            self.compiled_path = compiled_dir
            self.model_path = models_dir
            self.output_path = output_dir
            self.manifest = engine.manifest

        async def compile(self):
            await self.engine.compile_all()
            # Save manifest to disk so output() can read previous state
            _save_manifest(self.config.manifest_path, self.engine.manifest)
            return self.engine.manifest

    return ProjectHelper(engine, config, tmp_path)


@pytest.fixture(autouse=True)
def setup_mock(mock_agent: MagicMock) -> None:
    """Ensure mock_agent is active for all tests."""
    pass


async def test_output_returns_none_on_first_compile(output_project):
    """Test output() returns None on first compile."""
    (output_project.model_path / "first.md").write_text(
        """---
name: First Compile Test
---
# Content

{% if output() %}
Previous output exists: {{ output().content | length }} chars
{% else %}
No previous output
{% endif %}
"""
    )

    await output_project.compile()

    doc = output_project.manifest.get_document("project://first.md")
    assert doc is not None

    output_path = output_project.compiled_path / doc.output_path
    output = output_path.read_text()

    # First compile should show no previous output
    assert "No previous output" in output
    assert "Previous output exists" not in output


async def test_output_reads_published_file(output_project):
    """Test output() reads from published output directory."""
    (output_project.model_path / "published.md").write_text(
        """---
name: Published Test
---
# Initial Content

{% if output() %}
Previous: {{ output().content | length }} chars
{% else %}
First run
{% endif %}
"""
    )

    # First compile
    await output_project.compile()

    doc = output_project.manifest.get_document("project://published.md")
    assert doc is not None
    first_output = (output_project.compiled_path / doc.output_path).read_text()
    assert "First run" in first_output

    # Modify model and recompile
    (output_project.model_path / "published.md").write_text(
        """---
name: Published Test
---
# Modified Content with more text

{% if output() %}
Previous: {{ output().content | length }} chars
{% else %}
First run
{% endif %}
"""
    )

    await output_project.compile()

    second_output = (output_project.compiled_path / doc.output_path).read_text()

    # Should have previous length
    assert "Previous:" in second_output
    assert "First run" not in second_output


async def test_output_cached_reads_from_artifact_cache(output_project):
    """Test output(cached=True) reads from Colin's artifact cache."""
    (output_project.model_path / "cached.md").write_text(
        """---
name: Cached Test
---
# Initial Content

{% if output(cached=True) %}
Cached: {{ output(cached=True).content | length }} chars
{% else %}
First run
{% endif %}
"""
    )

    # First compile
    await output_project.compile()

    doc = output_project.manifest.get_document("project://cached.md")
    assert doc is not None
    first_output = (output_project.compiled_path / doc.output_path).read_text()
    assert "First run" in first_output

    # Modify and recompile
    (output_project.model_path / "cached.md").write_text(
        """---
name: Cached Test
---
# Modified Content

{% if output(cached=True) %}
Cached: {{ output(cached=True).content | length }} chars
{% else %}
First run
{% endif %}
"""
    )

    await output_project.compile()

    second_output = (output_project.compiled_path / doc.output_path).read_text()
    assert "Cached:" in second_output
    assert str(len(first_output)) in second_output


async def test_output_preserves_manual_edits(output_project):
    """Test output() sees manual edits to published file."""
    (output_project.model_path / "manual.md").write_text(
        """---
name: Manual Edit Test
---
# Content

{% if output() %}
Previous content: {{ output().content }}
{% else %}
First run
{% endif %}
"""
    )

    # First compile
    await output_project.compile()

    doc = output_project.manifest.get_document("project://manual.md")
    assert doc is not None

    # Manually edit the published output file
    published_path = output_project.output_path / doc.output_path
    published_path.write_text("MANUALLY EDITED CONTENT")

    # Modify model and recompile
    (output_project.model_path / "manual.md").write_text(
        """---
name: Manual Edit Test
---
# Modified

{% if output() %}
Previous content: {{ output().content }}
{% else %}
First run
{% endif %}
"""
    )

    await output_project.compile()

    final_output = (output_project.compiled_path / doc.output_path).read_text()

    # Should see the manual edit
    assert "MANUALLY EDITED CONTENT" in final_output


async def test_output_cached_ignores_manual_edits(output_project):
    """Test output(cached=True) ignores manual edits to published file."""
    (output_project.model_path / "cached_vs_manual.md").write_text(
        """---
name: Cached vs Manual Test
---
# Original Content

Done
"""
    )

    # First compile
    await output_project.compile()

    doc = output_project.manifest.get_document("project://cached_vs_manual.md")
    assert doc is not None

    # Manually edit the published output file
    published_path = output_project.output_path / doc.output_path
    published_path.write_text("MANUALLY EDITED")

    # Now create a model that checks both
    (output_project.model_path / "cached_vs_manual.md").write_text(
        """---
name: Cached vs Manual Test
---
# Check Both

Published: {{ output().content if output() else 'none' }}
Cached: {{ output(cached=True).content if output(cached=True) else 'none' }}
"""
    )

    await output_project.compile()

    final_output = (output_project.compiled_path / doc.output_path).read_text()

    # output() should see manual edit, output(cached=True) should see original
    assert "MANUALLY EDITED" in final_output
    assert "Original Content" in final_output


async def test_output_does_not_affect_staleness(output_project):
    """Test output() does not create ref dependencies."""
    (output_project.model_path / "no_staleness.md").write_text(
        """---
name: No Staleness Test
---
# Content

{% if output() %}
Has previous
{% else %}
No previous
{% endif %}
"""
    )

    await output_project.compile()

    doc = output_project.manifest.get_document("project://no_staleness.md")
    assert doc is not None

    # Check that no self-referential refs were created
    for ref in doc.refs:
        # Should not have a ref to itself
        assert ref.args.get("path") != doc.output_path


async def test_output_works_outside_defer_blocks(output_project):
    """Test output() works in main template body, not just defer blocks."""
    (output_project.model_path / "main_body.md").write_text(
        """---
name: Main Body Test
---
# Content

Output available: {{ 'yes' if output() else 'no' }}
"""
    )

    # First compile - output() should return None
    await output_project.compile()

    doc = output_project.manifest.get_document("project://main_body.md")
    assert doc is not None
    first_output = (output_project.compiled_path / doc.output_path).read_text()
    assert "Output available: no" in first_output

    # Modify and recompile - output() should now return content
    (output_project.model_path / "main_body.md").write_text(
        """---
name: Main Body Test
---
# Modified

Output available: {{ 'yes' if output() else 'no' }}
"""
    )

    await output_project.compile()

    second_output = (output_project.compiled_path / doc.output_path).read_text()
    assert "Output available: yes" in second_output


async def test_output_sections_accessor(output_project):
    """Test output().sections provides access to previous sections."""
    (output_project.model_path / "sections.md").write_text(
        """---
name: Sections Test
---
{% section intro %}
## Introduction
Welcome!
{% endsection %}

{% section body %}
## Body
Content here.
{% endsection %}

Done.
"""
    )

    # First compile
    await output_project.compile()

    doc = output_project.manifest.get_document("project://sections.md")
    assert doc is not None

    # Modify to access previous sections
    (output_project.model_path / "sections.md").write_text(
        """---
name: Sections Test
---
{% section intro %}
## Introduction
Updated!
{% endsection %}

{% if output(cached=True) %}
Previous sections: {{ output(cached=True).sections.keys() | list | join(', ') }}
{% else %}
No previous
{% endif %}
"""
    )

    await output_project.compile()

    second_output = (output_project.compiled_path / doc.output_path).read_text()
    assert "Previous sections:" in second_output
    assert "intro" in second_output
    assert "body" in second_output


async def test_output_in_defer_block(output_project):
    """Test output() works inside defer blocks."""
    (output_project.model_path / "defer_output.md").write_text(
        """---
name: Defer Output Test
---
# Content

{% defer %}
{% if output(cached=True) %}
Previous length: {{ output(cached=True).content | length }}
{% else %}
No previous
{% endif %}
{% enddefer %}
"""
    )

    # First compile
    await output_project.compile()

    doc = output_project.manifest.get_document("project://defer_output.md")
    assert doc is not None
    first_output = (output_project.compiled_path / doc.output_path).read_text()
    assert "No previous" in first_output

    # Modify and recompile
    (output_project.model_path / "defer_output.md").write_text(
        """---
name: Defer Output Test
---
# Modified Content

{% defer %}
{% if output(cached=True) %}
Previous length: {{ output(cached=True).content | length }}
{% else %}
No previous
{% endif %}
{% enddefer %}
"""
    )

    await output_project.compile()

    second_output = (output_project.compiled_path / doc.output_path).read_text()
    assert "Previous length:" in second_output
    assert str(len(first_output)) in second_output
