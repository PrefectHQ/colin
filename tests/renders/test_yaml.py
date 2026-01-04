"""Tests for YAML renderer."""

import pytest

from colin.renders.yaml import YAMLRenderer


class TestYAMLRenderer:
    """Tests for YAMLRenderer."""

    @pytest.fixture
    def renderer(self):
        return YAMLRenderer()

    def test_headers_to_yaml_keys(self, renderer):
        content = """## name
Alice

## role
admin"""
        result = renderer.render(content, "project://test.md")
        assert result.content == "name: Alice\nrole: admin\n"

    def test_markdown_list_to_yaml_sequence(self, renderer):
        content = """## tags
- python
- data
- ml"""
        result = renderer.render(content, "project://test.md")
        assert result.content == "tags:\n- python\n- data\n- ml\n"

    def test_nested_structure(self, renderer):
        content = """## user
### name
Alice

### email
alice@example.com"""
        result = renderer.render(content, "project://test.md")
        assert "user:" in result.content
        assert "name: Alice" in result.content
        assert "email: alice@example.com" in result.content

    def test_yaml_fence_passthrough(self, renderer):
        content = """```yaml
name: John
age: 30
```"""
        result = renderer.render(content, "project://test.md")
        assert result.content == "name: John\nage: 30\n"

    def test_json_fence_also_works(self, renderer):
        content = """```json
{"name": "John", "age": 30}
```"""
        result = renderer.render(content, "project://test.md")
        assert "name: John" in result.content
        assert "age: 30" in result.content

    def test_raw_yaml_passthrough(self, renderer):
        content = "name: John\nage: 30"
        result = renderer.render(content, "project://test.md")
        assert result.content == "name: John\nage: 30\n"

    def test_output_filename(self, renderer):
        content = "## key\nvalue"
        result = renderer.render(content, "project://config.md")
        assert result.filename == "config.yaml"
