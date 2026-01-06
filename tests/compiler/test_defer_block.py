"""Tests for defer block extension."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from colin.api.project import ProjectConfig
from colin.compiler import CompileEngine
from colin.providers.storage.file import FileStorage


@pytest.fixture
def defer_project(tmp_path: Path):
    """Create a test project with defer blocks."""
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    build_dir = tmp_path / ".colin"
    build_dir.mkdir()
    compiled_dir = build_dir / "compiled"
    compiled_dir.mkdir()

    # Document with defer block accessing rendered.content
    (models_dir / "content.md").write_text(
        """---
name: Content Test
---
# Main Content
This is the main content.

{% defer %}
## Summary
Content length: {{ rendered.content | length }} characters
{% enddefer %}
"""
    )

    # Document with defer block accessing rendered.sections
    (models_dir / "sections.md").write_text(
        """---
name: Sections Test
---
{% section intro %}
## Introduction
Welcome to the document.
{% endsection %}

{% section body %}
## Body
Main content here.
{% endsection %}

{% defer %}
## Table of Contents
{% for name in rendered.sections.keys() %}
- {{ name }}
{% endfor %}
{% enddefer %}
"""
    )

    # Document with variables outside defer block
    (models_dir / "variables.md").write_text(
        """---
name: Variables Test
---
{% set title = "My Document" %}
{% set version = "1.0" %}

# {{ title }}

{% defer %}
## Metadata
- Title: {{ title }}
- Version: {{ version }}
- Content: {{ rendered.content | length }} chars
{% enddefer %}
"""
    )

    # Document with multiple defer blocks
    (models_dir / "multiple.md").write_text(
        """---
name: Multiple Defer Blocks
---
# Content

{% defer %}
First defer: {{ rendered.content | length }}
{% enddefer %}

More content.

{% defer %}
Second defer: {{ rendered.content | length }}
{% enddefer %}
"""
    )

    # Document with sections in defer block
    (models_dir / "sections_in_defer.md").write_text(
        """---
name: Sections in Defer
---
# Main Content

{% defer %}
{% section summary %}
## Summary
This is a summary section defined inside a defer block.
{% endsection %}
{% enddefer %}
"""
    )

    config = ProjectConfig(
        name="defer-test",
        project_root=tmp_path,
        model_path=models_dir,
        output_path=tmp_path / "output",
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
            self.manifest = engine.manifest

        async def compile(self):
            await self.engine.compile_all()
            return self.engine.manifest

    return ProjectHelper(engine, config, tmp_path)


@pytest.fixture(autouse=True)
def setup_mock(mock_agent: MagicMock) -> None:
    """Ensure mock_agent is active for all tests."""
    pass


async def test_defer_block_with_rendered_content(defer_project):
    """Test defer block can access rendered.content."""
    try:
        await defer_project.compile()
    except Exception as e:
        print(f"Compilation error: {e}")
        if hasattr(e, "errors"):
            for uri, errors in e.errors.items():  # type: ignore[attr-defined]
                print(f"  {uri}:")
                for error in errors:
                    print(f"    {error}")
        raise

    content_doc = defer_project.manifest.get_document("project://content.md")
    assert content_doc is not None

    # Read the compiled output
    output_path = defer_project.compiled_path / content_doc.output_path
    output = output_path.read_text()

    # Should contain the summary with content length
    assert "## Summary" in output
    assert "Content length:" in output
    assert "characters" in output
    # Should not contain markers
    assert "<!--COLIN:DEFER" not in output


async def test_defer_block_with_rendered_sections(defer_project):
    """Test defer block can access rendered.sections."""
    await defer_project.compile()

    sections_doc = defer_project.manifest.get_document("project://sections.md")
    assert sections_doc is not None

    output_path = defer_project.compiled_path / sections_doc.output_path
    output = output_path.read_text()

    # Should contain TOC with section names
    assert "## Table of Contents" in output
    assert "- intro" in output
    assert "- body" in output
    # Should not contain markers
    assert "<!--COLIN:" not in output


async def test_defer_block_with_variables_from_first_pass(defer_project):
    """Test defer block can access variables set outside the block."""
    await defer_project.compile()

    variables_doc = defer_project.manifest.get_document("project://variables.md")
    assert variables_doc is not None

    output_path = defer_project.compiled_path / variables_doc.output_path
    output = output_path.read_text()

    # Should contain metadata with variables from first pass
    assert "## Metadata" in output
    assert "- Title: My Document" in output
    assert "- Version: 1.0" in output
    assert "- Content:" in output
    assert "chars" in output


async def test_multiple_defer_blocks(defer_project):
    """Test multiple defer blocks in same document."""
    await defer_project.compile()

    multiple_doc = defer_project.manifest.get_document("project://multiple.md")
    assert multiple_doc is not None

    output_path = defer_project.compiled_path / multiple_doc.output_path
    output = output_path.read_text()

    # Both defer blocks should be rendered
    assert "First defer:" in output
    assert "Second defer:" in output
    # Both should show same content length (they see the same first pass)
    lines = [line for line in output.split("\n") if "defer:" in line]
    assert len(lines) == 2
    # Both should have same length value
    first_length = lines[0].split(":")[-1].strip()
    second_length = lines[1].split(":")[-1].strip()
    assert first_length == second_length


async def test_sections_in_defer_block(defer_project):
    """Test defer blocks can define sections."""
    await defer_project.compile()

    doc = defer_project.manifest.get_document("project://sections_in_defer.md")
    assert doc is not None

    # Section should be captured
    assert "summary" in doc.sections
    assert "Summary" in doc.sections["summary"]


async def test_previous_rendered_is_none_on_first_compile(defer_project):
    """Test previous_rendered is None on first compile."""
    # Create a document that uses previous_rendered
    (defer_project.model_path / "previous.md").write_text(
        """---
name: Previous Test
---
# Content

{% defer %}
{% if previous_rendered %}
Previous: {{ previous_rendered.content | length }}
{% else %}
No previous render
{% endif %}
{% enddefer %}
"""
    )

    await defer_project.compile()

    doc = defer_project.manifest.get_document("project://previous.md")
    assert doc is not None

    output_path = defer_project.compiled_path / doc.output_path
    output = output_path.read_text()

    # First compile should show no previous render
    assert "No previous render" in output
    assert "Previous:" not in output


async def test_previous_rendered_populated_on_second_compile(defer_project):
    """Test previous_rendered is populated on second compile."""
    # Create a document that uses previous_rendered
    (defer_project.model_path / "previous2.md").write_text(
        """---
name: Previous Test 2
---
# Content Version 1

{% defer %}
{% if previous_rendered %}
Previous length: {{ previous_rendered.content | length }}
{% else %}
No previous
{% endif %}
{% enddefer %}
"""
    )

    # First compile
    await defer_project.compile()

    doc = defer_project.manifest.get_document("project://previous2.md")
    assert doc is not None
    output_path = defer_project.compiled_path / doc.output_path
    first_output = output_path.read_text()

    assert "No previous" in first_output

    # Modify document
    (defer_project.model_path / "previous2.md").write_text(
        """---
name: Previous Test 2
---
# Content Version 2 with more text

{% defer %}
{% if previous_rendered %}
Previous length: {{ previous_rendered.content | length }}
{% else %}
No previous
{% endif %}
{% enddefer %}
"""
    )

    # Second compile
    try:
        await defer_project.compile()
    except Exception as e:
        print(f"Second compilation error: {e}")
        if hasattr(e, "errors"):
            for uri, errors in e.errors.items():  # type: ignore[attr-defined]
                print(f"  {uri}:")
                for error in errors:
                    print(f"    {error}")
                    import traceback

                    traceback.print_exception(type(error), error, error.__traceback__)
        raise

    second_output = output_path.read_text()

    # Should have previous length
    assert "Previous length:" in second_output
    assert "No previous" not in second_output
    # The previous length should be the length of first_output
    assert str(len(first_output)) in second_output


async def test_defer_block_format_aware_sections(tmp_path: Path, mock_agent: MagicMock):
    """Test defer blocks work with JSON output and format-aware sections."""
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    build_dir = tmp_path / ".colin"
    build_dir.mkdir()
    compiled_dir = build_dir / "compiled"
    compiled_dir.mkdir()

    (models_dir / "config.json.md").write_text(
        """---
colin:
  output:
    format: json
---
{% section database %}
## host
localhost

## port
5432
{% endsection %}

{% defer %}
{% section metadata %}
## sections_count
{{ rendered.sections.keys() | list | length }}
{% endsection %}
{% enddefer %}
"""
    )

    config = ProjectConfig(
        name="json-test",
        project_root=tmp_path,
        model_path=models_dir,
        output_path=tmp_path / "output",
        manifest_path=build_dir / "manifest.json",
    )
    artifact_storage = FileStorage(base_path=compiled_dir)
    engine = CompileEngine(config=config, artifact_storage=artifact_storage)

    await engine.compile_all()

    doc = engine.manifest.get_document("project://config.json.md")
    assert doc is not None
    assert doc.output_path is not None

    output_path = compiled_dir / doc.output_path
    import json

    output = json.loads(output_path.read_text())

    # JSON renderer flattens all sections into root object
    # Should have fields from both database and metadata sections
    assert "host" in output
    assert output["host"] == "localhost"
    assert "port" in output
    assert int(output["port"]) == 5432

    # sections_count should be 1 because defer block sees only "database" section
    # during second pass (metadata section is created by the defer block itself)
    assert "sections_count" in output
    assert int(output["sections_count"]) == 1

    # Both sections should be captured in document metadata
    assert "database" in doc.sections
    assert "metadata" in doc.sections
