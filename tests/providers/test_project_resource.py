"""Tests for Project provider and ProjectResource."""

from pathlib import Path

import pytest

from colin.models import Ref
from colin.providers.project import ProjectResource


class TestProjectResource:
    """Tests for ProjectResource class."""

    def test_data_json_returns_parsed_dict(self) -> None:
        """data property parses JSON content and returns dict."""
        ref = Ref(provider="project", connection="", method="get", args={"path": "config.json"})
        resource = ProjectResource(
            content='{"api_key": "secret123", "users": [{"name": "Alice"}]}',
            ref=ref,
            relative_path="config.json",
            output_path=Path("/tmp"),
        )

        data = resource.data

        assert isinstance(data, dict)
        assert data["api_key"] == "secret123"
        assert data["users"][0]["name"] == "Alice"

    def test_data_json_returns_parsed_list(self) -> None:
        """data property parses JSON array and returns list."""
        ref = Ref(provider="project", connection="", method="get", args={"path": "items.json"})
        resource = ProjectResource(
            content='[{"id": 1}, {"id": 2}]',
            ref=ref,
            relative_path="items.json",
            output_path=Path("/tmp"),
        )

        data = resource.data

        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["id"] == 1

    def test_data_yaml_returns_parsed_dict(self) -> None:
        """data property parses YAML content and returns dict."""
        ref = Ref(provider="project", connection="", method="get", args={"path": "config.yaml"})
        resource = ProjectResource(
            content="api_key: secret123\nusers:\n  - name: Alice",
            ref=ref,
            relative_path="config.yaml",
            output_path=Path("/tmp"),
        )

        data = resource.data

        assert isinstance(data, dict)
        assert data["api_key"] == "secret123"
        assert data["users"][0]["name"] == "Alice"

    def test_data_yaml_yml_extension(self) -> None:
        """data property works with .yml extension."""
        ref = Ref(provider="project", connection="", method="get", args={"path": "config.yml"})
        resource = ProjectResource(
            content="key: value",
            ref=ref,
            relative_path="config.yml",
            output_path=Path("/tmp"),
        )

        data = resource.data

        assert isinstance(data, dict)
        assert data["key"] == "value"

    def test_data_markdown_returns_string(self) -> None:
        """data property returns string content for markdown files."""
        ref = Ref(provider="project", connection="", method="get", args={"path": "readme.md"})
        content = "# Hello\n\nThis is markdown content."
        resource = ProjectResource(
            content=content,
            ref=ref,
            relative_path="readme.md",
            output_path=Path("/tmp"),
        )

        data = resource.data

        assert isinstance(data, str)
        assert data == content
        assert data == resource.content  # Same as .content

    def test_data_other_format_returns_string(self) -> None:
        """data property returns string for non-JSON/YAML formats."""
        ref = Ref(provider="project", connection="", method="get", args={"path": "script.py"})
        content = "print('hello')"
        resource = ProjectResource(
            content=content,
            ref=ref,
            relative_path="script.py",
            output_path=Path("/tmp"),
        )

        data = resource.data

        assert isinstance(data, str)
        assert data == content

    def test_data_empty_json_returns_empty_dict(self) -> None:
        """data property returns empty dict for empty JSON content."""
        ref = Ref(provider="project", connection="", method="get", args={"path": "empty.json"})
        resource = ProjectResource(
            content="",
            ref=ref,
            relative_path="empty.json",
            output_path=Path("/tmp"),
        )

        data = resource.data

        assert isinstance(data, dict)
        assert data == {}

    def test_data_empty_yaml_returns_empty_dict(self) -> None:
        """data property returns empty dict for empty YAML content."""
        ref = Ref(provider="project", connection="", method="get", args={"path": "empty.yaml"})
        resource = ProjectResource(
            content="",
            ref=ref,
            relative_path="empty.yaml",
            output_path=Path("/tmp"),
        )

        data = resource.data

        assert isinstance(data, dict)
        assert data == {}

    def test_data_caches_parsed_result(self) -> None:
        """data property caches parsed result to avoid re-parsing."""
        ref = Ref(provider="project", connection="", method="get", args={"path": "config.json"})
        resource = ProjectResource(
            content='{"key": "value"}',
            ref=ref,
            relative_path="config.json",
            output_path=Path("/tmp"),
        )

        data1 = resource.data
        data2 = resource.data

        # Should return same object (cached)
        assert data1 is data2
        assert data1 == {"key": "value"}

    def test_data_invalid_json_raises_error(self) -> None:
        """data property raises JSONDecodeError for invalid JSON."""
        ref = Ref(provider="project", connection="", method="get", args={"path": "bad.json"})
        resource = ProjectResource(
            content="{invalid json}",
            ref=ref,
            relative_path="bad.json",
            output_path=Path("/tmp"),
        )

        with pytest.raises(Exception):  # json.JSONDecodeError
            _ = resource.data

    def test_data_works_with_private_files(self) -> None:
        """data property works for private files (no path access needed)."""
        ref = Ref(provider="project", connection="", method="get", args={"path": "_private.json"})
        resource = ProjectResource(
            content='{"secret": "data"}',
            ref=ref,
            relative_path="_private.json",
            output_path=Path("/tmp"),
            is_private=True,
        )

        data = resource.data

        assert isinstance(data, dict)
        assert data["secret"] == "data"
        # Should not raise error about path access
