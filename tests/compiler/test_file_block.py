"""Tests for the {% file %} block extension."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from colin.api.project import ProjectConfig
from colin.compiler import CompileEngine
from colin.providers.storage.file import FileStorage


@pytest.fixture
def file_project(tmp_path: Path):
    """Create a test project for file block tests."""
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    build_dir = tmp_path / ".colin"
    build_dir.mkdir()
    compiled_dir = build_dir / "compiled"
    compiled_dir.mkdir()
    output_dir = tmp_path / "output"

    config = ProjectConfig(
        name="file-test",
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
            from colin.api.compile import _save_manifest

            await self.engine.compile_all()
            # Save manifest to disk so get_stale_files() can read it
            _save_manifest(self.config.manifest_path, self.engine.manifest)
            return self.engine.manifest

    return ProjectHelper(engine, config, tmp_path)


@pytest.fixture(autouse=True)
def setup_mock(mock_agent: MagicMock) -> None:
    """Ensure mock_agent is active for all tests."""
    pass


async def test_basic_file_creation(file_project):
    """Test basic file creation with {% file %} block."""
    (file_project.model_path / "generator.md").write_text(
        """---
name: Generator
---
# Generator

{% file "output.txt" %}
Hello from file block!
{% endfile %}

Generator complete.
"""
    )

    await file_project.compile()

    # File should be created in compiled directory
    file_path = file_project.compiled_path / "output.txt"
    assert file_path.exists()
    content = file_path.read_text()
    assert "Hello from file block!" in content

    # File should be published to output directory (inherits from public source)
    output_file = file_project.output_path / "output.txt"
    assert output_file.exists()


async def test_file_with_variables(file_project):
    """Test file block renders Jinja variables."""
    (file_project.model_path / "generator.md").write_text(
        """---
name: Generator
---
{% set name = "Alice" %}
{% set version = "1.0" %}

{% file "config.txt" %}
name: {{ name }}
version: {{ version }}
{% endfile %}

Done.
"""
    )

    await file_project.compile()

    file_path = file_project.compiled_path / "config.txt"
    content = file_path.read_text()
    assert "name: Alice" in content
    assert "version: 1.0" in content


async def test_file_with_json_format(file_project):
    """Test file block with format='json' applies JSON renderer."""
    (file_project.model_path / "generator.md").write_text(
        """---
name: Generator
---
{% file "data.json" format="json" %}
## name
Alice

## age
30
{% endfile %}

Done.
"""
    )

    await file_project.compile()

    import json

    file_path = file_project.compiled_path / "data.json"
    content = json.loads(file_path.read_text())
    assert content["name"] == "Alice"
    assert int(content["age"]) == 30


async def test_file_with_item_blocks(file_project):
    """Test file block with item blocks for JSON arrays."""
    (file_project.model_path / "generator.md").write_text(
        """---
name: Generator
---
{% file "users.json" format="json" %}
{% for name in ["Alice", "Bob", "Charlie"] %}
{% item %}
## name
{{ name }}
{% enditem %}
{% endfor %}
{% endfile %}

Done.
"""
    )

    await file_project.compile()

    import json

    file_path = file_project.compiled_path / "users.json"
    content = json.loads(file_path.read_text())
    assert isinstance(content, list)
    assert len(content) == 3
    assert content[0]["name"] == "Alice"
    assert content[1]["name"] == "Bob"
    assert content[2]["name"] == "Charlie"


async def test_file_publish_false(file_project):
    """Test file with publish=false stays in compiled directory."""
    (file_project.model_path / "generator.md").write_text(
        """---
name: Generator
---
{% file "private.txt" publish=false %}
This is private.
{% endfile %}

Done.
"""
    )

    await file_project.compile()

    # Should exist in compiled
    compiled_file = file_project.compiled_path / "private.txt"
    assert compiled_file.exists()

    # Should NOT exist in output
    output_file = file_project.output_path / "private.txt"
    assert not output_file.exists()


async def test_file_publish_true_from_private_source(file_project):
    """Test file with publish=true from private source is published."""
    (file_project.model_path / "_generator.md").write_text(
        """---
name: Private Generator
---
{% file "public_output.txt" publish=true %}
This should be public despite private source.
{% endfile %}

Done.
"""
    )

    await file_project.compile()

    # Main output should NOT be published (private source)
    main_output = file_project.output_path / "_generator.md"
    assert not main_output.exists()

    # File output should be published (explicit publish=true)
    output_file = file_project.output_path / "public_output.txt"
    assert output_file.exists()


async def test_private_source_inherits_private_file_outputs(file_project):
    """Test file outputs from private source default to not published."""
    (file_project.model_path / "_generator.md").write_text(
        """---
name: Private Generator
---
{% file "also_private.txt" %}
This inherits private from source.
{% endfile %}

Done.
"""
    )

    await file_project.compile()

    # File should exist in compiled
    compiled_file = file_project.compiled_path / "also_private.txt"
    assert compiled_file.exists()

    # File should NOT be published (inherits from private source)
    output_file = file_project.output_path / "also_private.txt"
    assert not output_file.exists()


async def test_multiple_file_outputs(file_project):
    """Test multiple file blocks in single source."""
    (file_project.model_path / "generator.md").write_text(
        """---
name: Generator
---
{% file "file1.txt" %}
Content 1
{% endfile %}

{% file "file2.txt" %}
Content 2
{% endfile %}

{% file "subdir/file3.txt" %}
Content 3
{% endfile %}

Done.
"""
    )

    await file_project.compile()

    # All files should exist
    assert (file_project.compiled_path / "file1.txt").exists()
    assert (file_project.compiled_path / "file2.txt").exists()
    assert (file_project.compiled_path / "subdir" / "file3.txt").exists()

    # All should be published
    assert (file_project.output_path / "file1.txt").exists()
    assert (file_project.output_path / "file2.txt").exists()
    assert (file_project.output_path / "subdir" / "file3.txt").exists()


async def test_file_outputs_tracked_in_manifest(file_project):
    """Test file outputs are tracked in manifest."""
    (file_project.model_path / "generator.md").write_text(
        """---
name: Generator
---
{% file "tracked.json" format="json" %}
## key
value
{% endfile %}

Done.
"""
    )

    await file_project.compile()

    doc = file_project.manifest.get_document("project://generator.md")
    assert doc is not None
    assert "tracked.json" in doc.file_outputs

    # File output metadata should include format
    meta = doc.file_outputs["tracked.json"]
    assert meta.format == "json"


async def test_manifest_reverse_index_includes_file_outputs(file_project):
    """Test manifest can find source document by file output path."""
    (file_project.model_path / "generator.md").write_text(
        """---
name: Generator
---
{% file "findme.txt" %}
Content
{% endfile %}

Done.
"""
    )

    await file_project.compile()

    # Should find generator.md as producer of findme.txt
    doc = file_project.manifest.get_document_by_output_path("findme.txt")
    assert doc is not None
    assert doc.uri == "project://generator.md"


async def test_duplicate_path_error(file_project):
    """Test duplicate file path in same document raises error."""
    from colin.exceptions import MultipleCompilationErrors

    (file_project.model_path / "generator.md").write_text(
        """---
name: Generator
---
{% file "duplicate.txt" %}
First
{% endfile %}

{% file "duplicate.txt" %}
Second
{% endfile %}

Done.
"""
    )

    with pytest.raises(MultipleCompilationErrors) as exc_info:
        await file_project.compile()

    # Check nested errors for duplicate message
    errors = exc_info.value.errors
    error_messages = [str(e) for uri_errors in errors.values() for e in uri_errors]
    assert any("duplicate" in msg.lower() for msg in error_messages)


async def test_absolute_path_error(file_project):
    """Test absolute path in file block raises error."""
    from colin.exceptions import MultipleCompilationErrors

    (file_project.model_path / "generator.md").write_text(
        """---
name: Generator
---
{% file "/absolute/path.txt" %}
Content
{% endfile %}

Done.
"""
    )

    with pytest.raises(MultipleCompilationErrors) as exc_info:
        await file_project.compile()

    # Check nested errors for path issue
    errors = exc_info.value.errors
    error_messages = [str(e) for uri_errors in errors.values() for e in uri_errors]
    assert any("absolute" in msg.lower() or "relative" in msg.lower() for msg in error_messages)


async def test_path_escape_error(file_project):
    """Test path with .. raises error."""
    from colin.exceptions import MultipleCompilationErrors

    (file_project.model_path / "generator.md").write_text(
        """---
name: Generator
---
{% file "../escape.txt" %}
Content
{% endfile %}

Done.
"""
    )

    with pytest.raises(MultipleCompilationErrors) as exc_info:
        await file_project.compile()

    # Check nested errors for path issue
    errors = exc_info.value.errors
    error_messages = [str(e) for uri_errors in errors.values() for e in uri_errors]
    assert any(".." in msg for msg in error_messages)


async def test_file_block_does_not_emit_to_main_output(file_project):
    """Test file block content doesn't appear in main document output."""
    (file_project.model_path / "generator.md").write_text(
        """---
name: Generator
---
Before file block.

{% file "separate.txt" %}
This should NOT appear in main output.
{% endfile %}

After file block.
"""
    )

    await file_project.compile()

    # Read main output
    doc = file_project.manifest.get_document("project://generator.md")
    main_output = (file_project.compiled_path / doc.output_path).read_text()

    assert "Before file block" in main_output
    assert "After file block" in main_output
    assert "This should NOT appear in main output" not in main_output


async def test_sections_in_file_block_scoped_to_file(file_project):
    """Test sections inside file block are scoped to that file only."""
    (file_project.model_path / "generator.md").write_text(
        """---
name: Generator
---
{% section main_section %}
## Main
This is in the main document.
{% endsection %}

{% file "output.md" %}
{% section file_section %}
## File Section
This is in the file output.
{% endsection %}
{% endfile %}

Done.
"""
    )

    await file_project.compile()

    doc = file_project.manifest.get_document("project://generator.md")
    assert doc is not None

    # Main document should have main_section
    assert "main_section" in doc.sections
    # Main document should NOT have file_section (scoped to file)
    assert "file_section" not in doc.sections

    # File output metadata should have file_section
    assert "output.md" in doc.file_outputs
    file_meta = doc.file_outputs["output.md"]
    assert "file_section" in file_meta.sections


async def test_file_with_for_loop(file_project):
    """Test generating multiple files with a for loop."""
    (file_project.model_path / "generator.md").write_text(
        """---
name: Generator
---
{% for user in ["alice", "bob"] %}
{% file user ~ ".txt" %}
User: {{ user }}
{% endfile %}
{% endfor %}

Generated user files.
"""
    )

    await file_project.compile()

    # Both files should exist
    assert (file_project.compiled_path / "alice.txt").exists()
    assert (file_project.compiled_path / "bob.txt").exists()

    alice_content = (file_project.compiled_path / "alice.txt").read_text()
    assert "User: alice" in alice_content

    bob_content = (file_project.compiled_path / "bob.txt").read_text()
    assert "User: bob" in bob_content


async def test_file_outputs_not_reported_as_stale(file_project):
    """Test file outputs are not reported as stale files."""
    from colin.api.project import get_stale_files

    (file_project.model_path / "generator.md").write_text(
        """---
name: Generator
---
{% file "data.json" format="json" %}
## key
value
{% endfile %}

Done.
"""
    )

    await file_project.compile()

    # File output should exist in output/
    assert (file_project.output_path / "data.json").exists()

    # File output should NOT be reported as stale
    stale = get_stale_files(file_project.config)
    stale_relative = [str(p.relative_to(file_project.output_path)) for p in stale]
    assert "data.json" not in stale_relative


async def test_private_file_outputs_not_reported_as_stale_in_compiled(file_project):
    """Test private file outputs are not stale in .colin/compiled/."""
    from colin.api.project import get_stale_files

    (file_project.model_path / "generator.md").write_text(
        """---
name: Generator
---
{% file "private.json" format="json" publish=false %}
## key
value
{% endfile %}

Done.
"""
    )

    await file_project.compile()

    # File should exist in compiled but not output
    assert (file_project.compiled_path / "private.json").exists()
    assert not (file_project.output_path / "private.json").exists()

    # Should not be reported as stale in compiled dir
    stale = get_stale_files(file_project.config, include_compiled=True)
    stale_relative = [
        str(p.relative_to(file_project.compiled_path))
        for p in stale
        if file_project.compiled_path in p.parents or p.parent == file_project.compiled_path
    ]
    assert "private.json" not in stale_relative
