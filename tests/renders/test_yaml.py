"""Tests for YAML renderer."""

import pytest

from colin.models import CompiledDocument, Frontmatter
from colin.renders.yaml import YAMLRenderer


def make_doc(uri: str, output: str) -> CompiledDocument:
    """Create a minimal CompiledDocument for testing."""
    return CompiledDocument(
        uri=uri,
        output=output,
        frontmatter=Frontmatter(),
        source_hash="test",
        output_hash="test",
    )


class TestYAMLRenderer:
    """Tests for YAMLRenderer."""

    @pytest.fixture
    def renderer(self):
        return YAMLRenderer()

    def test_headers_to_yaml_keys(self, renderer):
        doc = make_doc(
            uri="test",
            output="""## name
Alice

## role
admin""",
        )
        result = renderer.render(doc)
        assert result.content == "name: Alice\nrole: admin\n"

    def test_markdown_list_to_yaml_sequence(self, renderer):
        doc = make_doc(
            uri="test",
            output="""## tags
- python
- data
- ml""",
        )
        result = renderer.render(doc)
        assert result.content == "tags:\n- python\n- data\n- ml\n"

    def test_nested_structure(self, renderer):
        doc = make_doc(
            uri="test",
            output="""## user
### name
Alice

### email
alice@example.com""",
        )
        result = renderer.render(doc)
        assert "user:" in result.content
        assert "name: Alice" in result.content
        assert "email: alice@example.com" in result.content

    def test_yaml_fence_passthrough(self, renderer):
        doc = make_doc(
            uri="test",
            output="""```yaml
name: John
age: 30
```""",
        )
        result = renderer.render(doc)
        assert result.content == "name: John\nage: 30\n"

    def test_json_fence_also_works(self, renderer):
        doc = make_doc(
            uri="test",
            output="""```json
{"name": "John", "age": 30}
```""",
        )
        result = renderer.render(doc)
        assert "name: John" in result.content
        assert "age: 30" in result.content

    def test_raw_yaml_passthrough(self, renderer):
        doc = make_doc(uri="test", output="name: John\nage: 30")
        result = renderer.render(doc)
        assert result.content == "name: John\nage: 30\n"

    def test_output_filename(self, renderer):
        doc = make_doc(uri="config", output="## key\nvalue")
        result = renderer.render(doc)
        assert result.filename == "config.yaml"
