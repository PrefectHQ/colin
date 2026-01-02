"""Tests for markdown-to-structure parsing."""

import json

import pytest

from colin.compiler.extensions.item_block import ITEM_END_MARKER, ITEM_START_MARKER
from colin.renders.markdown_parser import (
    MarkdownStructureError,
    parse_markdown_to_structure,
)


class TestHeaderToKey:
    """Tests for header-to-key mapping."""

    def test_single_header_with_text(self):
        content = """## name
John Doe"""
        result = parse_markdown_to_structure(content)
        assert result == {"name": "John Doe"}

    def test_multiple_headers(self):
        content = """## name
John Doe

## email
john@example.com"""
        result = parse_markdown_to_structure(content)
        assert result == {"name": "John Doe", "email": "john@example.com"}

    def test_header_with_multiline_text(self):
        content = """## description
This is a long description
that spans multiple lines."""
        result = parse_markdown_to_structure(content)
        assert result == {"description": "This is a long description\nthat spans multiple lines."}

    def test_empty_section(self):
        content = """## empty

## next
has content"""
        result = parse_markdown_to_structure(content)
        assert result == {"empty": "", "next": "has content"}

    def test_h1_headers_work(self):
        content = """# name
John"""
        result = parse_markdown_to_structure(content)
        assert result == {"name": "John"}

    def test_mixed_header_levels_at_root(self):
        # The shallowest level becomes root
        content = """## name
John

### nickname
Johnny"""
        result = parse_markdown_to_structure(content)
        # nickname is nested under name because it's deeper
        assert result == {"name": {"_content": "John", "nickname": "Johnny"}}


class TestHeaderWithList:
    """Tests for headers with markdown lists."""

    def test_simple_list(self):
        content = """## tags
- python
- data
- ml"""
        result = parse_markdown_to_structure(content)
        assert result == {"tags": ["python", "data", "ml"]}

    def test_list_with_spaces(self):
        content = """## items
- first item
- second item"""
        result = parse_markdown_to_structure(content)
        assert result == {"items": ["first item", "second item"]}

    def test_mixed_text_and_list_is_text(self):
        # If there's text before the list, treat whole thing as text
        content = """## description
Some intro text
- item one
- item two"""
        result = parse_markdown_to_structure(content)
        # This is NOT a list because it has text before the list items
        assert result == {"description": "Some intro text\n- item one\n- item two"}


class TestHeaderWithJsonFence:
    """Tests for headers with JSON fences."""

    def test_json_number(self):
        content = """## age
```json
50
```"""
        result = parse_markdown_to_structure(content)
        assert result == {"age": 50}

    def test_json_object(self):
        content = """## config
```json
{"debug": true, "level": 3}
```"""
        result = parse_markdown_to_structure(content)
        assert result == {"config": {"debug": True, "level": 3}}

    def test_json_array(self):
        content = """## scores
```json
[1, 2, 3, 4, 5]
```"""
        result = parse_markdown_to_structure(content)
        assert result == {"scores": [1, 2, 3, 4, 5]}

    def test_json_null(self):
        content = """## value
```json
null
```"""
        result = parse_markdown_to_structure(content)
        assert result == {"value": None}

    def test_json_boolean(self):
        content = """## active
```json
true
```"""
        result = parse_markdown_to_structure(content)
        assert result == {"active": True}


class TestNestedHeaders:
    """Tests for nested header structures."""

    def test_simple_nesting(self):
        content = """## user
### name
John
### age
```json
30
```"""
        result = parse_markdown_to_structure(content)
        assert result == {"user": {"name": "John", "age": 30}}

    def test_deep_nesting(self):
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
        result = parse_markdown_to_structure(content)
        assert result == {
            "config": {
                "database": {"host": "localhost", "port": 5432},
                "cache": {"enabled": True},
            }
        }

    def test_skipped_header_levels(self):
        # H2 then H5 - should still nest properly
        content = """## top
##### deep
value"""
        result = parse_markdown_to_structure(content)
        assert result == {"top": {"deep": "value"}}

    def test_very_deep_header_nesting(self):
        # 12 # characters after H2 - relative depth matters
        content = """## root
############ deep
nested value"""
        result = parse_markdown_to_structure(content)
        assert result == {"root": {"deep": "nested value"}}

    def test_sibling_nested_sections(self):
        content = """## user1
### name
Alice

## user2
### name
Bob"""
        result = parse_markdown_to_structure(content)
        assert result == {"user1": {"name": "Alice"}, "user2": {"name": "Bob"}}


class TestItemBlocks:
    """Tests for {% item %} block markers."""

    def test_simple_items(self):
        content = f"""{ITEM_START_MARKER}
## name
Alice
{ITEM_END_MARKER}
{ITEM_START_MARKER}
## name
Bob
{ITEM_END_MARKER}"""
        result = parse_markdown_to_structure(content)
        assert result == [{"name": "Alice"}, {"name": "Bob"}]

    def test_items_with_multiple_fields(self):
        content = f"""{ITEM_START_MARKER}
## id
```json
1
```
## name
Alice
{ITEM_END_MARKER}
{ITEM_START_MARKER}
## id
```json
2
```
## name
Bob
{ITEM_END_MARKER}"""
        result = parse_markdown_to_structure(content)
        assert result == [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
        ]

    def test_items_with_nested_structure(self):
        content = f"""{ITEM_START_MARKER}
## user
### name
Alice
### roles
- admin
- user
{ITEM_END_MARKER}"""
        result = parse_markdown_to_structure(content)
        assert result == [{"user": {"name": "Alice", "roles": ["admin", "user"]}}]

    def test_nested_items_in_headers(self):
        content = f"""## users
{ITEM_START_MARKER}
Alice
{ITEM_END_MARKER}
{ITEM_START_MARKER}
Bob
{ITEM_END_MARKER}"""
        result = parse_markdown_to_structure(content)
        assert result == {"users": ["Alice", "Bob"]}


class TestLiteralJsonPassthrough:
    """Tests for literal JSON passthrough."""

    def test_json_object_passthrough(self):
        content = """```json
{"name": "John", "age": 30}
```"""
        result = parse_markdown_to_structure(content)
        assert result == {"name": "John", "age": 30}

    def test_json_array_passthrough(self):
        content = """```json
[1, 2, 3]
```"""
        result = parse_markdown_to_structure(content)
        assert result == [1, 2, 3]

    def test_json_string_passthrough(self):
        content = """```json
"hello world"
```"""
        result = parse_markdown_to_structure(content)
        assert result == "hello world"

    def test_json_number_passthrough(self):
        content = """```json
42
```"""
        result = parse_markdown_to_structure(content)
        assert result == 42

    def test_complex_json_passthrough(self):
        content = """```json
{
  "users": [
    {"name": "Alice", "active": true},
    {"name": "Bob", "active": false}
  ],
  "count": 2
}
```"""
        result = parse_markdown_to_structure(content)
        assert result == {
            "users": [
                {"name": "Alice", "active": True},
                {"name": "Bob", "active": False},
            ],
            "count": 2,
        }


class TestLiteralJsonWithoutFence:
    """Tests for raw JSON (without fence) being passed through."""

    def test_raw_json_object(self):
        content = '{"name": "John"}'
        result = parse_markdown_to_structure(content)
        assert result == {"name": "John"}

    def test_raw_json_array(self):
        content = "[1, 2, 3]"
        result = parse_markdown_to_structure(content)
        assert result == [1, 2, 3]


class TestPlainTextFallback:
    """Tests for plain text fallback to string literal."""

    def test_plain_text_becomes_string(self):
        content = "Just some plain text without structure"
        result = parse_markdown_to_structure(content)
        assert result == "Just some plain text without structure"

    def test_multiline_plain_text(self):
        content = """Line one
Line two
Line three"""
        result = parse_markdown_to_structure(content)
        assert result == "Line one\nLine two\nLine three"

    def test_empty_content(self):
        result = parse_markdown_to_structure("")
        assert result == ""

    def test_whitespace_only(self):
        result = parse_markdown_to_structure("   \n   \n   ")
        assert result == ""


class TestValidationErrors:
    """Tests for validation errors."""

    def test_duplicate_keys_error(self):
        content = """## name
First

## name
Second"""
        with pytest.raises(MarkdownStructureError, match="Duplicate key 'name'"):
            parse_markdown_to_structure(content)

    def test_content_before_first_header_error(self):
        content = """Some preamble text

## name
John"""
        with pytest.raises(MarkdownStructureError, match="Content found before first header"):
            parse_markdown_to_structure(content)

    def test_mixed_items_and_headers_at_root_error(self):
        # Items BEFORE headers = error (ambiguous root structure)
        content = f"""{ITEM_START_MARKER}
item content
{ITEM_END_MARKER}

## name
John"""
        with pytest.raises(MarkdownStructureError, match="Cannot mix.*item.*blocks with headers"):
            parse_markdown_to_structure(content)

    def test_invalid_json_in_fence_error(self):
        content = """## data
```json
{invalid json}
```"""
        with pytest.raises(json.JSONDecodeError):
            parse_markdown_to_structure(content)

    def test_malformed_raw_json_error(self):
        # Trailing comma makes this invalid JSON
        content = '{"foo": "bar",}'
        with pytest.raises(json.JSONDecodeError):
            parse_markdown_to_structure(content)

    def test_malformed_raw_json_array_error(self):
        content = "[1, 2, 3,]"
        with pytest.raises(json.JSONDecodeError):
            parse_markdown_to_structure(content)


class TestEdgeCases:
    """Tests for edge cases."""

    def test_header_with_special_characters(self):
        content = """## user-name
John

## email_address
john@example.com"""
        result = parse_markdown_to_structure(content)
        assert result == {"user-name": "John", "email_address": "john@example.com"}

    def test_header_with_spaces(self):
        content = """## First Name
John"""
        result = parse_markdown_to_structure(content)
        assert result == {"First Name": "John"}

    def test_preserves_internal_whitespace(self):
        content = """## code
def hello():
    print("world")"""
        result = parse_markdown_to_structure(content)
        assert result == {"code": 'def hello():\n    print("world")'}

    def test_json_fence_with_surrounding_content_treated_as_text(self):
        # If there's content around the fence, it's not "sole" fence
        content = """Intro text
```json
{"a": 1}
```
Outro text"""
        result = parse_markdown_to_structure(content)
        # Not a sole fence, so becomes plain text (with warning)
        assert 'Intro text\n```json\n{"a": 1}\n```\nOutro text' == result

    def test_multiple_json_fences_not_passthrough(self):
        content = """```json
1
```
```json
2
```"""
        # Multiple fences means not a sole fence, so treated as text
        result = parse_markdown_to_structure(content)
        assert "```json" in result
