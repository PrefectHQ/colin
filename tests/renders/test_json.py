"""Tests for JSON renderer."""

import json

import pytest

from colin.renders.json import JSONRenderer


class TestJSONRenderer:
    """Tests for JSONRenderer."""

    @pytest.fixture
    def renderer(self):
        return JSONRenderer()

    def test_headers_to_json_keys(self, renderer):
        content = """## name
Alice

## role
admin"""
        result = renderer.render(content, "project://test.md")
        parsed = json.loads(result.content)
        assert parsed == {"name": "Alice", "role": "admin"}

    def test_markdown_list_to_json_array(self, renderer):
        content = """## tags
- python
- data
- ml"""
        result = renderer.render(content, "project://test.md")
        parsed = json.loads(result.content)
        assert parsed == {"tags": ["python", "data", "ml"]}

    def test_nested_headers(self, renderer):
        content = """## user
### name
Alice

### email
alice@example.com"""
        result = renderer.render(content, "project://test.md")
        parsed = json.loads(result.content)
        assert parsed == {"user": {"name": "Alice", "email": "alice@example.com"}}

    def test_json_fence_passthrough(self, renderer):
        content = """```json
{"name": "John", "age": 30}
```"""
        result = renderer.render(content, "project://test.md")
        parsed = json.loads(result.content)
        assert parsed == {"name": "John", "age": 30}

    def test_json_fence_in_header_for_literals(self, renderer):
        content = """## name
Alice

## age
```json
30
```

## active
```json
true
```"""
        result = renderer.render(content, "project://test.md")
        parsed = json.loads(result.content)
        assert parsed == {"name": "Alice", "age": 30, "active": True}

    def test_raw_json_passthrough(self, renderer):
        result = renderer.render('{"key": "value"}', "project://test.md")
        parsed = json.loads(result.content)
        assert parsed == {"key": "value"}

    def test_output_filename_extension(self, renderer):
        result = renderer.render("## key\nvalue", "project://config.md")
        assert result.filename == "config.json"

    def test_output_is_pretty_printed(self, renderer):
        content = """## name
Alice"""
        result = renderer.render(content, "project://test.md")
        # Pretty printed JSON has newlines
        assert "\n" in result.content
        assert "  " in result.content  # 2-space indent

    def test_unicode_preserved(self, renderer):
        content = """## greeting
こんにちは

## emoji
🎉"""
        result = renderer.render(content, "project://test.md")
        parsed = json.loads(result.content)
        assert parsed == {"greeting": "こんにちは", "emoji": "🎉"}
        # Ensure not escaped
        assert "こんにちは" in result.content
        assert "🎉" in result.content

    def test_malformed_json_raises_error(self, renderer):
        with pytest.raises(json.JSONDecodeError):
            renderer.render('{"foo": "bar",}', "project://test.md")

    def test_complex_nested_structure(self, renderer):
        content = """## config
### database
#### host
localhost

#### port
```json
5432
```

### cache
#### enabled
```json
true
```"""
        result = renderer.render(content, "project://test.md")
        parsed = json.loads(result.content)
        assert parsed == {
            "config": {
                "database": {"host": "localhost", "port": 5432},
                "cache": {"enabled": True},
            }
        }

    def test_content_with_children_uses_content_key(self, renderer):
        """When a header has both text and child headers, text goes to _content."""
        content = """## user
Some introductory text about the user.

### name
Alice

### role
admin"""
        result = renderer.render(content, "project://test.md")
        parsed = json.loads(result.content)
        assert parsed == {
            "user": {
                "_content": "Some introductory text about the user.",
                "name": "Alice",
                "role": "admin",
            }
        }
