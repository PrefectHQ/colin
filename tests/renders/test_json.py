"""Tests for JSON renderer."""

import json

import pytest

from colin.models import CompiledDocument, Frontmatter
from colin.renders.json import JSONRenderer


def make_doc(uri: str, output: str) -> CompiledDocument:
    """Create a minimal CompiledDocument for testing."""
    return CompiledDocument(
        uri=uri,
        output=output,
        frontmatter=Frontmatter(),
        source_hash="test",
        output_hash="test",
    )


class TestJSONRenderer:
    """Tests for JSONRenderer."""

    @pytest.fixture
    def renderer(self):
        return JSONRenderer()

    def test_headers_to_json_keys(self, renderer):
        doc = make_doc(
            uri="test",
            output="""## name
Alice

## role
admin""",
        )
        result = renderer.render(doc)
        parsed = json.loads(result.content)
        assert parsed == {"name": "Alice", "role": "admin"}

    def test_markdown_list_to_json_array(self, renderer):
        doc = make_doc(
            uri="test",
            output="""## tags
- python
- data
- ml""",
        )
        result = renderer.render(doc)
        parsed = json.loads(result.content)
        assert parsed == {"tags": ["python", "data", "ml"]}

    def test_nested_headers(self, renderer):
        doc = make_doc(
            uri="test",
            output="""## user
### name
Alice

### email
alice@example.com""",
        )
        result = renderer.render(doc)
        parsed = json.loads(result.content)
        assert parsed == {"user": {"name": "Alice", "email": "alice@example.com"}}

    def test_json_fence_passthrough(self, renderer):
        doc = make_doc(
            uri="test",
            output="""```json
{"name": "John", "age": 30}
```""",
        )
        result = renderer.render(doc)
        parsed = json.loads(result.content)
        assert parsed == {"name": "John", "age": 30}

    def test_json_fence_in_header_for_literals(self, renderer):
        doc = make_doc(
            uri="test",
            output="""## name
Alice

## age
```json
30
```

## active
```json
true
```""",
        )
        result = renderer.render(doc)
        parsed = json.loads(result.content)
        assert parsed == {"name": "Alice", "age": 30, "active": True}

    def test_raw_json_passthrough(self, renderer):
        doc = make_doc(uri="test", output='{"key": "value"}')
        result = renderer.render(doc)
        parsed = json.loads(result.content)
        assert parsed == {"key": "value"}

    def test_output_filename_extension(self, renderer):
        doc = make_doc(uri="config", output="## key\nvalue")
        result = renderer.render(doc)
        assert result.filename == "config.json"

    def test_output_is_pretty_printed(self, renderer):
        doc = make_doc(
            uri="test",
            output="""## name
Alice""",
        )
        result = renderer.render(doc)
        # Pretty printed JSON has newlines
        assert "\n" in result.content
        assert "  " in result.content  # 2-space indent

    def test_unicode_preserved(self, renderer):
        doc = make_doc(
            uri="test",
            output="""## greeting
こんにちは

## emoji
🎉""",
        )
        result = renderer.render(doc)
        parsed = json.loads(result.content)
        assert parsed == {"greeting": "こんにちは", "emoji": "🎉"}
        # Ensure not escaped
        assert "こんにちは" in result.content
        assert "🎉" in result.content

    def test_malformed_json_raises_error(self, renderer):
        doc = make_doc(uri="test", output='{"foo": "bar",}')
        with pytest.raises(json.JSONDecodeError):
            renderer.render(doc)

    def test_complex_nested_structure(self, renderer):
        doc = make_doc(
            uri="test",
            output="""## config
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
```""",
        )
        result = renderer.render(doc)
        parsed = json.loads(result.content)
        assert parsed == {
            "config": {
                "database": {"host": "localhost", "port": 5432},
                "cache": {"enabled": True},
            }
        }

    def test_content_with_children_uses_content_key(self, renderer):
        """When a header has both text and child headers, text goes to _content."""
        doc = make_doc(
            uri="test",
            output="""## user
Some introductory text about the user.

### name
Alice

### role
admin""",
        )
        result = renderer.render(doc)
        parsed = json.loads(result.content)
        assert parsed == {
            "user": {
                "_content": "Some introductory text about the user.",
                "name": "Alice",
                "role": "admin",
            }
        }
