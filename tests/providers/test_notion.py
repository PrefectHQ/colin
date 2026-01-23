"""Tests for Notion provider.

Note: NotionProvider is imported inside test classes to avoid circular import
issues at module load time.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from colin.models import Ref


class TestNotionProvider:
    """Tests for NotionProvider."""

    @pytest.fixture
    def NotionProvider(self):
        """Lazy import to avoid circular import at collection time."""
        from colin.providers.notion import NotionProvider

        return NotionProvider

    def test_namespace_is_notion(self, NotionProvider) -> None:
        """Provider has correct namespace."""
        provider = NotionProvider.from_config(None, {})

        assert provider.namespace == "notion"

    def test_creates_without_config(self, NotionProvider) -> None:
        """Create provider with no configuration."""
        provider = NotionProvider.from_config(None, {})

        assert provider.namespace == "notion"
        assert provider._connection == ""

    def test_creates_with_name(self, NotionProvider) -> None:
        """Create provider with instance name."""
        provider = NotionProvider.from_config("workspace", {})

        assert provider._connection == "workspace"

    def test_get_functions_includes_page_and_search(self, NotionProvider) -> None:
        """Provider exposes page and search functions."""
        provider = NotionProvider.from_config(None, {})
        functions = provider.get_functions()

        assert "page" in functions
        assert "search" in functions
        assert len(functions) == 2


class TestNotionPageResource:
    """Tests for NotionPageResource."""

    @pytest.fixture
    def NotionPageResource(self):
        """Lazy import."""
        from colin.providers.notion import NotionPageResource

        return NotionPageResource

    def test_version_uses_last_edited_time(self, NotionPageResource) -> None:
        """Version is based on last_edited_time."""
        edit_time = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        ref = Ref(provider="notion", connection="", method="page", args={"url_or_id": "abc"})

        resource = NotionPageResource(
            content="# Test Page\n\nContent here.",
            ref=ref,
            page_id="abc123",
            title="Test Page",
            url="https://notion.so/abc123",
            last_edited_time=edit_time,
        )

        assert resource.version == edit_time.isoformat()

    def test_exposes_all_attributes(self, NotionPageResource) -> None:
        """Resource exposes expected attributes."""
        edit_time = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        create_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        ref = Ref(provider="notion", connection="", method="page", args={"url_or_id": "abc"})

        resource = NotionPageResource(
            content="Page content",
            ref=ref,
            page_id="page-123",
            title="My Page",
            url="https://notion.so/page-123",
            last_edited_time=edit_time,
            created_time=create_time,
            is_archived=True,
        )

        assert resource.content == "Page content"
        assert resource.page_id == "page-123"
        assert resource.title == "My Page"
        assert resource.url == "https://notion.so/page-123"
        assert resource.last_edited_time == edit_time
        assert resource.created_time == create_time
        assert resource.is_archived is True


class TestNotionSearchResource:
    """Tests for NotionSearchResource."""

    @pytest.fixture
    def resources(self):
        """Lazy import both resource classes."""
        from colin.providers.notion import NotionPageResource, NotionSearchResource

        return NotionPageResource, NotionSearchResource

    def test_version_is_hash_of_pages(self, resources) -> None:
        """Version is deterministic hash of all page IDs and edit times."""
        NotionPageResource, NotionSearchResource = resources
        edit_time = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

        page1 = NotionPageResource(
            content="Page 1",
            ref=Ref(provider="notion", connection="", method="page", args={"url_or_id": "a"}),
            page_id="page-a",
            title="Page A",
            url="https://notion.so/a",
            last_edited_time=edit_time,
        )
        page2 = NotionPageResource(
            content="Page 2",
            ref=Ref(provider="notion", connection="", method="page", args={"url_or_id": "b"}),
            page_id="page-b",
            title="Page B",
            url="https://notion.so/b",
            last_edited_time=edit_time,
        )

        search_ref = Ref(provider="notion", connection="", method="search", args={"query": "test"})
        resource = NotionSearchResource(
            content="Page A\nPage B",
            ref=search_ref,
            query="test",
            pages=[page1, page2],
        )

        # Version should be a 16-char hex hash
        assert len(resource.version) == 16
        assert all(c in "0123456789abcdef" for c in resource.version)

    def test_version_changes_when_page_changes(self, resources) -> None:
        """Version changes when any page's edit time changes."""
        NotionPageResource, NotionSearchResource = resources
        time1 = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        time2 = datetime(2024, 1, 15, 11, 0, 0, tzinfo=timezone.utc)

        def make_search(edit_time: datetime) -> NotionSearchResource:
            page = NotionPageResource(
                content="Page",
                ref=Ref(provider="notion", connection="", method="page", args={"url_or_id": "a"}),
                page_id="page-a",
                title="Page A",
                url="https://notion.so/a",
                last_edited_time=edit_time,
            )
            return NotionSearchResource(
                content="Page A",
                ref=Ref(provider="notion", connection="", method="search", args={"query": "test"}),
                query="test",
                pages=[page],
            )

        resource1 = make_search(time1)
        resource2 = make_search(time2)

        assert resource1.version != resource2.version

    def test_iterable(self, resources) -> None:
        """Search resource is iterable over pages."""
        NotionPageResource, NotionSearchResource = resources
        edit_time = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

        pages = [
            NotionPageResource(
                content=f"Page {i}",
                ref=Ref(
                    provider="notion", connection="", method="page", args={"url_or_id": str(i)}
                ),
                page_id=f"page-{i}",
                title=f"Page {i}",
                url=f"https://notion.so/{i}",
                last_edited_time=edit_time,
            )
            for i in range(3)
        ]

        resource = NotionSearchResource(
            content="Page 0\nPage 1\nPage 2",
            ref=Ref(provider="notion", connection="", method="search", args={"query": "test"}),
            query="test",
            pages=pages,
        )

        assert len(resource) == 3
        assert list(resource) == pages

    def test_content_is_titles(self, resources) -> None:
        """Content is newline-separated page titles."""
        NotionPageResource, NotionSearchResource = resources
        edit_time = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

        pages = [
            NotionPageResource(
                content="Content A",
                ref=Ref(provider="notion", connection="", method="page", args={"url_or_id": "a"}),
                page_id="a",
                title="First Page",
                url="https://notion.so/a",
                last_edited_time=edit_time,
            ),
            NotionPageResource(
                content="Content B",
                ref=Ref(provider="notion", connection="", method="page", args={"url_or_id": "b"}),
                page_id="b",
                title="Second Page",
                url="https://notion.so/b",
                last_edited_time=edit_time,
            ),
        ]

        resource = NotionSearchResource(
            content="First Page\nSecond Page",
            ref=Ref(provider="notion", connection="", method="search", args={"query": "test"}),
            query="test",
            pages=pages,
        )

        assert resource.content == "First Page\nSecond Page"
        assert resource.query == "test"


class TestNotionProviderIntegration:
    """Integration tests for NotionProvider (with mocked MCP client)."""

    @pytest.fixture
    def NotionProvider(self):
        """Lazy import."""
        from colin.providers.notion import NotionProvider

        return NotionProvider

    async def test_page_creates_correct_ref(self, NotionProvider) -> None:
        """page() creates a Ref with correct arguments."""
        provider = NotionProvider.from_config(None, {})

        # Mock the MCP client
        mock_client = AsyncMock()
        mock_result = MagicMock()
        mock_result.content = [MagicMock(text="# Test Page\n\nContent")]
        mock_client.call_tool = AsyncMock(return_value=mock_result)

        provider._client = mock_client

        # Patch get_compile_context to return None (no tracking)
        with patch("colin.providers.notion.get_compile_context", return_value=None):
            resource = await provider.page("https://notion.so/test-page")

        assert resource.ref().provider == "notion"
        assert resource.ref().method == "page"
        assert resource.ref().args == {"url_or_id": "https://notion.so/test-page"}

        mock_client.call_tool.assert_called_once_with(
            "notion-fetch", {"id": "https://notion.so/test-page"}
        )

    async def test_search_creates_correct_ref(self, NotionProvider) -> None:
        """search() creates a Ref with correct arguments."""
        provider = NotionProvider.from_config(None, {})

        # Mock the MCP client
        mock_client = AsyncMock()
        mock_result = MagicMock()
        mock_result.content = [MagicMock(text="")]  # Empty search results
        mock_client.call_tool = AsyncMock(return_value=mock_result)

        provider._client = mock_client

        with patch("colin.providers.notion.get_compile_context", return_value=None):
            resource = await provider.search("onboarding docs")

        assert resource.ref().provider == "notion"
        assert resource.ref().method == "search"
        # Note: watch defaults to False for search, so it's not in args
        assert resource.ref().args == {"query": "onboarding docs", "limit": 20}

        mock_client.call_tool.assert_called_once_with("notion-search", {"query": "onboarding docs"})
