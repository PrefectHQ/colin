"""Notion provider for fetching pages from Notion workspaces."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, ClassVar

from fastmcp import Client
from fastmcp.client.auth import OAuth
from pydantic import validate_call
from typing_extensions import Self

from colin.compiler.cache import get_compile_context
from colin.models import Ref
from colin.providers.base import Provider
from colin.providers.oauth_store import get_oauth_store
from colin.resources import Resource

# Notion's hosted MCP server URL
NOTION_MCP_URL = "https://mcp.notion.com/mcp"


class NotionPageResource(Resource):
    """Resource returned by NotionProvider.page() and search results."""

    def __init__(
        self,
        content: str,
        ref: Ref,
        page_id: str,
        title: str,
        url: str,
        last_edited_time: datetime,
        created_time: datetime | None = None,
        is_archived: bool = False,
    ) -> None:
        """Initialize a Notion page resource.

        Args:
            content: Page content as markdown.
            ref: The Ref for this resource.
            page_id: Notion page ID.
            title: Page title.
            url: Notion page URL.
            last_edited_time: When the page was last modified.
            created_time: When the page was created.
            is_archived: Whether the page is archived.
        """
        super().__init__(content, ref)
        self.page_id = page_id
        self.title = title
        self.url = url
        self.last_edited_time = last_edited_time
        self.created_time = created_time
        self.is_archived = is_archived

    @property
    def version(self) -> str:
        """Use last_edited_time as version for efficient staleness checking."""
        return self.last_edited_time.isoformat()


class NotionSearchResource(Resource):
    """Resource returned by NotionProvider.search()."""

    def __init__(
        self,
        content: str,
        ref: Ref,
        query: str,
        pages: list[NotionPageResource],
    ) -> None:
        """Initialize a Notion search resource.

        Args:
            content: Newline-separated page titles.
            ref: The Ref for this resource.
            query: The search query used.
            pages: List of page resources (eagerly fetched).
        """
        super().__init__(content, ref)
        self.query = query
        self.pages = pages

    @property
    def version(self) -> str:
        """Version based on all page IDs and their edit times."""
        # Create a deterministic hash of all pages' identities and versions
        parts = sorted(f"{p.page_id}:{p.last_edited_time.isoformat()}" for p in self.pages)
        combined = "\n".join(parts)
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

    def __iter__(self) -> Any:
        """Allow iteration over pages."""
        return iter(self.pages)

    def __len__(self) -> int:
        """Return number of pages."""
        return len(self.pages)


class NotionProvider(Provider):
    """Provider for fetching pages from Notion workspaces.

    Uses Notion's hosted MCP server for OAuth and API access.

    Template usage:
        {{ colin.notion.page("https://notion.so/page-id").content }}
        {{ colin.notion.page("abc123def456").content }}

        {% for page in colin.notion.search("onboarding") %}
            {{ page.title }}: {{ page.content }}
        {% endfor %}

    Configuration:
        [providers.notion]
        # No configuration needed - auto-connects to Notion MCP
        # OAuth flow triggered on first use
    """

    namespace: ClassVar[str] = "notion"

    _client: Client | None = None
    _connection: str = ""

    @classmethod
    def from_config(cls, name: str | None, config: dict[str, Any]) -> Self:
        """Create Notion provider from configuration.

        Args:
            name: Instance name (unused - only one Notion workspace per OAuth).
            config: Provider configuration (currently unused).

        Returns:
            Configured NotionProvider instance.
        """
        instance = cls()
        instance._connection = name or ""
        return instance

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        """Manage MCP client lifecycle."""
        # Create persistent token storage (with optional encryption)
        token_storage = get_oauth_store()
        oauth = OAuth(mcp_url=NOTION_MCP_URL, token_storage=token_storage)  # type: ignore[arg-type]

        try:
            async with Client(NOTION_MCP_URL, auth=oauth) as client:
                self._client = client
                yield
        except Exception as e:
            raise RuntimeError(
                f"Failed to connect to Notion MCP server\n"
                f"  URL: {NOTION_MCP_URL}\n"
                f"  Error: {e}\n\n"
                f"If this is an authentication error, try clearing your OAuth tokens:\n"
                f"  colin mcp auth clear"
            ) from None
        finally:
            self._client = None

    def _require_client(self) -> Client:
        """Get client, raising if not initialized."""
        if self._client is None:
            raise RuntimeError("NotionProvider not initialized - use within lifespan context")
        return self._client

    @validate_call
    async def page(self, url_or_id: str, *, watch: bool = True) -> NotionPageResource:
        """Fetch a Notion page by URL or ID.

        Args:
            url_or_id: Notion page URL or page ID.
            watch: Whether to track this ref for staleness (default True).

        Returns:
            NotionPageResource with page content and metadata.
        """
        client = self._require_client()

        # Call the notion-fetch tool (expects "id" parameter which can be URL or page ID)
        result = await client.call_tool("notion-fetch", {"id": url_or_id})

        # Parse the response
        page_data = self._parse_page_response(result)

        ref = Ref(
            provider=self.namespace,
            connection=self._connection,
            method="page",
            args={"url_or_id": url_or_id},
        )

        resource = NotionPageResource(
            content=page_data["content"],
            ref=ref,
            page_id=page_data["page_id"],
            title=page_data["title"],
            url=page_data["url"],
            last_edited_time=page_data["last_edited_time"],
            created_time=page_data.get("created_time"),
            is_archived=page_data.get("is_archived", False),
        )

        if watch:
            ctx = get_compile_context()
            if ctx:
                ctx.track(ref, resource.version)

        return resource

    @validate_call
    async def search(
        self, query: str, *, limit: int = 20, watch: bool = True
    ) -> NotionSearchResource:
        """Search Notion workspace for pages matching a query.

        Args:
            query: Search query string.
            limit: Maximum number of results to return (default 20).
            watch: Whether to track this ref for staleness (default True).

        Returns:
            NotionSearchResource with matching pages.
            Page content contains search highlights - use page() for full content.
        """
        client = self._require_client()

        # Call the notion-search tool
        result = await client.call_tool("notion-search", {"query": query})

        # Parse search results (returns highlights, not full content)
        search_data = self._parse_search_response(result)
        pages: list[NotionPageResource] = []

        for page_info in search_data["results"][:limit]:
            # Create a ref for each page
            page_ref = Ref(
                provider=self.namespace,
                connection=self._connection,
                method="page",
                args={"url_or_id": page_info["page_id"]},
            )

            page_resource = NotionPageResource(
                content=page_info["content"],  # Search highlight
                ref=page_ref,
                page_id=page_info["page_id"],
                title=page_info["title"],
                url=page_info["url"],
                last_edited_time=page_info["last_edited_time"],
                is_archived=page_info.get("is_archived", False),
            )
            pages.append(page_resource)

        # Content is newline-separated titles for simple rendering
        content = "\n".join(p.title for p in pages)

        ref = Ref(
            provider=self.namespace,
            connection=self._connection,
            method="search",
            args={"query": query, "limit": limit},
        )

        resource = NotionSearchResource(
            content=content,
            ref=ref,
            query=query,
            pages=pages,
        )

        if watch:
            ctx = get_compile_context()
            if ctx:
                ctx.track(ref, resource.version)

        return resource

    async def get_ref_version(self, ref: Ref) -> str:
        """Get current version for a ref.

        For pages, fetches metadata to get last_edited_time.
        For search, re-runs the search to get current results.
        """
        resource = await self._load_ref(ref)
        return resource.version

    def get_functions(self) -> dict[str, Callable[..., Awaitable[object]]]:
        """Return template functions this provider contributes."""
        return {
            "page": self.page,
            "search": self.search,
        }

    def _parse_page_response(self, result: Any) -> dict[str, Any]:
        """Parse notion-fetch tool response into page data.

        The response is JSON with: metadata, title, url, text
        """
        # Extract text content from CallToolResult
        raw_text = ""
        if hasattr(result, "content"):
            for block in result.content:
                if hasattr(block, "text"):
                    raw_text = block.text
                    break
        elif isinstance(result, str):
            raw_text = result
        else:
            raw_text = str(result)

        # Parse the JSON response
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            # Fallback if not JSON - use content hash for deterministic versioning
            content_hash = int(hashlib.sha256(raw_text.encode()).hexdigest()[:8], 16)
            epoch_seconds = content_hash % (50 * 365 * 24 * 3600)
            return {
                "content": raw_text,
                "page_id": hashlib.sha256(raw_text.encode()).hexdigest()[:16],
                "title": "Untitled",
                "url": "",
                "last_edited_time": datetime.fromtimestamp(epoch_seconds, tz=timezone.utc),
                "created_time": None,
                "is_archived": False,
            }

        # Extract the page content from the "text" field
        # The text field contains the enhanced markdown content
        content = data.get("text", "")

        # Extract page ID from URL
        url = data.get("url", "")
        page_id = url.split("/")[-1] if url else hashlib.sha256(content.encode()).hexdigest()[:16]

        # Try to extract timestamp from the text (format: "as of 2026-01-13T06:25:43.272Z")
        # Fall back to content-hash-based timestamp if not found (ensures deterministic versioning)
        last_edited: datetime | None = None
        timestamp_match = re.search(r"as of (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z)", content)
        if timestamp_match:
            try:
                last_edited = datetime.fromisoformat(
                    timestamp_match.group(1).replace("Z", "+00:00")
                )
            except ValueError:
                pass

        if last_edited is None:
            # Derive deterministic timestamp from content hash
            # This ensures version stays stable when content hasn't changed
            content_hash = int(hashlib.sha256(content.encode()).hexdigest()[:8], 16)
            # Map hash to a timestamp (seconds since epoch, bounded to reasonable range)
            epoch_seconds = content_hash % (50 * 365 * 24 * 3600)  # ~50 years range
            last_edited = datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)

        return {
            "content": content,
            "page_id": page_id,
            "title": data.get("title", "Untitled"),
            "url": url,
            "last_edited_time": last_edited,
            "created_time": None,
            "is_archived": False,
        }

    def _parse_search_response(self, result: Any) -> dict[str, Any]:
        """Parse notion-search tool response into search results.

        The response is JSON with: results array, type
        Each result has: title, url, type, highlight, timestamp, id
        """
        # Extract text content from CallToolResult
        raw_text = ""
        if hasattr(result, "content"):
            for block in result.content:
                if hasattr(block, "text"):
                    raw_text = block.text
                    break
        elif isinstance(result, str):
            raw_text = result
        else:
            raw_text = str(result)

        # Parse the JSON response
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            return {"results": []}

        results = []
        for item in data.get("results", []):
            # Parse timestamp like "Past day (2026-01-23)" or "6 days ago (2026-01-16)"
            timestamp_str = item.get("timestamp", "")
            last_edited = datetime.now(timezone.utc)
            date_match = re.search(r"\((\d{4}-\d{2}-\d{2})\)", timestamp_str)
            if date_match:
                try:
                    last_edited = datetime.strptime(date_match.group(1), "%Y-%m-%d").replace(
                        tzinfo=timezone.utc
                    )
                except ValueError:
                    pass

            results.append(
                {
                    "page_id": item.get("id", ""),
                    "title": item.get("title", "Untitled"),
                    "url": item.get("url", ""),
                    "content": item.get("highlight", ""),  # Search only returns highlight
                    "last_edited_time": last_edited,
                    "is_archived": False,
                }
            )

        return {"results": results}
