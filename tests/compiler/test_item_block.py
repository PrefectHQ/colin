"""Tests for the {% item %} block extension."""

from jinja2 import Environment

from colin.compiler.extensions.item_block import (
    ITEM_END_MARKER,
    ITEM_START_MARKER,
    ItemBlockExtension,
)


async def test_item_block_emits_markers():
    """Item block wraps content in markers."""
    env = Environment(enable_async=True, extensions=[ItemBlockExtension])
    template = env.from_string("{% item %}content{% enditem %}")

    result = await template.render_async()

    assert ITEM_START_MARKER in result
    assert ITEM_END_MARKER in result
    assert "content" in result


async def test_item_block_with_variables():
    """Item block renders variables inside."""
    env = Environment(enable_async=True, extensions=[ItemBlockExtension])
    template = env.from_string("{% item %}{{ name }}{% enditem %}")

    result = await template.render_async(name="Alice")

    assert "Alice" in result
    assert ITEM_START_MARKER in result


async def test_item_block_with_for_loop():
    """Item blocks work inside for loops."""
    env = Environment(enable_async=True, extensions=[ItemBlockExtension])
    template = env.from_string(
        "{% for name in names %}{% item %}{{ name }}{% enditem %}{% endfor %}"
    )

    result = await template.render_async(names=["Alice", "Bob", "Charlie"])

    # Should have 3 item blocks
    assert result.count(ITEM_START_MARKER) == 3
    assert result.count(ITEM_END_MARKER) == 3
    assert "Alice" in result
    assert "Bob" in result
    assert "Charlie" in result


async def test_item_block_preserves_whitespace():
    """Item block preserves content whitespace."""
    env = Environment(enable_async=True, extensions=[ItemBlockExtension])
    template = env.from_string(
        """{% item %}
## name
John

## age
30
{% enditem %}"""
    )

    result = await template.render_async()

    assert "## name" in result
    assert "John" in result
    assert "## age" in result


async def test_multiple_item_blocks():
    """Multiple separate item blocks work."""
    env = Environment(enable_async=True, extensions=[ItemBlockExtension])
    template = env.from_string(
        """{% item %}first{% enditem %}
{% item %}second{% enditem %}"""
    )

    result = await template.render_async()

    assert result.count(ITEM_START_MARKER) == 2
    assert "first" in result
    assert "second" in result


async def test_nested_item_blocks():
    """Nested item blocks work for arrays in objects."""
    env = Environment(enable_async=True, extensions=[ItemBlockExtension])
    template = env.from_string(
        """{% item %}
## users
{% for u in users %}{% item %}{{ u }}{% enditem %}{% endfor %}
{% enditem %}"""
    )

    result = await template.render_async(users=["Alice", "Bob"])

    # Outer item + 2 inner items = 3 start markers
    assert result.count(ITEM_START_MARKER) == 3
    assert "Alice" in result
    assert "Bob" in result
