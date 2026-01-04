"""Tests for ref() resolution."""

from collections.abc import Callable
from pathlib import Path

import pytest

from colin.cli import app


def test_ref_content_propagates(
    test_project: Path, output_dir: Path, mock_agent, cli: Callable[..., None]
):
    """Content from referenced doc appears in output."""
    cli("run", "--output", str(output_dir), "--quiet")

    welcome = (output_dir / "welcome.md").read_text()
    assert "Hello from greeting!" in welcome


def test_dependency_order(
    test_project: Path, output_dir: Path, mock_agent, cli: Callable[..., None]
):
    """Documents compile in dependency order."""
    cli("run", "--output", str(output_dir), "--quiet")

    summary = (output_dir / "summary.md").read_text()
    assert "Hello from greeting!" in summary
    assert "Welcome to Colin" in summary


def test_all_outputs_created(
    test_project: Path, output_dir: Path, mock_agent, cli: Callable[..., None]
):
    """All documents are compiled to output."""
    cli("run", "--output", str(output_dir), "--quiet")

    assert (output_dir / "greeting.md").exists()
    assert (output_dir / "welcome.md").exists()
    assert (output_dir / "summary.md").exists()


def test_missing_ref_fails(test_project: Path, output_dir: Path, mock_agent):
    """Referencing a non-existent document produces an error."""
    # Add a file with a bad ref
    models_dir = test_project / "models"
    (models_dir / "bad.md").write_text("""\
---
name: Bad
---
{{ ref('nonexistent.md').content }}
""")

    with pytest.raises(SystemExit) as exc_info:
        app(["run", "--output", str(output_dir), "--quiet"])

    assert exc_info.value.code == 1


def test_ref_data_json_returns_parsed_dict(
    test_project: Path, output_dir: Path, mock_agent, cli: Callable[..., None]
):
    """ref().data returns parsed dict for JSON files."""
    models_dir = test_project / "models"

    # Create a JSON output document
    (models_dir / "config.md").write_text("""\
---
name: Config
colin:
  output: json
---

## api_key
secret123

## users
```json
[{"name": "Alice"}, {"name": "Bob"}]
```
""")

    # Create a document that uses .data to access parsed JSON
    (models_dir / "consumer.md").write_text("""\
---
name: Consumer
---

API Key: {{ ref('config.json').data['api_key'] }}
First User: {{ ref('config.json').data['users'][0]['name'] }}
""")

    cli("run", "--output", str(output_dir), "--quiet")

    consumer = (output_dir / "consumer.md").read_text()
    assert "API Key: secret123" in consumer
    assert "First User: Alice" in consumer


def test_ref_data_yaml_returns_parsed_dict(
    test_project: Path, output_dir: Path, mock_agent, cli: Callable[..., None]
):
    """ref().data returns parsed dict for YAML files."""
    models_dir = test_project / "models"

    # Create a YAML output document
    (models_dir / "settings.md").write_text("""\
---
name: Settings
colin:
  output: yaml
---

## host
localhost

## port
```json
5432
```
""")

    # Create a document that uses .data to access parsed YAML
    (models_dir / "app.md").write_text("""\
---
name: App
---

Host: {{ ref('settings.yaml').data['host'] }}
Port: {{ ref('settings.yaml').data['port'] }}
""")

    cli("run", "--output", str(output_dir), "--quiet")

    app_output = (output_dir / "app.md").read_text()
    assert "Host: localhost" in app_output
    assert "Port: 5432" in app_output


def test_ref_data_markdown_returns_string(
    test_project: Path, output_dir: Path, mock_agent, cli: Callable[..., None]
):
    """ref().data returns string content for markdown files (same as .content)."""
    models_dir = test_project / "models"

    # Create a markdown document
    (models_dir / "readme.md").write_text("""\
---
name: Readme
---

# Documentation

This is the readme content.
""")

    # Create a document that uses .data on markdown
    (models_dir / "index.md").write_text("""\
---
name: Index
---

Content: {{ ref('readme.md').data }}
""")

    cli("run", "--output", str(output_dir), "--quiet")

    index = (output_dir / "index.md").read_text()
    # Should contain the compiled markdown content
    assert "Documentation" in index
    assert "readme content" in index
