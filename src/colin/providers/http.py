"""HTTP provider for fetching web resources."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING

import httpx

from colin.providers.base import Provider
from colin.providers.context import ProviderContext

if TYPE_CHECKING:
    from colin.models import RefResult


@dataclass
class HTTPResource:
    """Domain object returned by http.get()."""

    uri: str
    content: str
    content_type: str | None = None
    updated: datetime | None = None

    @property
    def last_updated(self) -> datetime:
        """When this resource was last modified."""
        return self.updated or datetime.now(timezone.utc)

    def to_ref_result(self) -> RefResult:
        """Convert to RefResult for dependency tracking."""
        from colin.models import RefResult

        return RefResult(
            name=self.uri.split("/")[-1] or self.uri,
            description=None,
            content=self.content,
            template="",
            updated=self.last_updated,
            uri=self.uri,
            source=self,
        )


class HTTPProvider(Provider):
    """Provider for http:// and https:// URIs.

    Provides web content fetching with proper HTTP semantics.
    """

    schemes = ["http", "https"]

    def __init__(self, timeout: float = 30.0) -> None:
        """Initialize HTTP provider.

        Args:
            timeout: Request timeout in seconds.
        """
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def read(self, uri: str) -> str:
        """Fetch content from URL.

        Args:
            uri: Full URL (e.g., 'https://example.com/data.json').

        Returns:
            Response body as string.

        Raises:
            FileNotFoundError: If URL returns 404.
            httpx.HTTPStatusError: For other HTTP errors.
        """
        client = await self._get_client()
        response = await client.get(uri)

        if response.status_code == 404:
            raise FileNotFoundError(f"URL not found: {uri}")

        response.raise_for_status()
        return response.text

    async def get_last_updated(self, uri: str) -> datetime | None:
        """Get last modified time via HEAD request.

        Args:
            uri: Full URL.

        Returns:
            Last-Modified datetime, or None if not available.
        """
        try:
            client = await self._get_client()
            response = await client.head(uri)

            if response.status_code >= 400:
                return None

            last_modified = response.headers.get("last-modified")
            if last_modified:
                return parsedate_to_datetime(last_modified)

            return None
        except httpx.HTTPError:
            return None

    def get_functions(self) -> dict[str, Callable[..., Awaitable[object]]]:
        return {"get": self._template_get}

    def _normalize_url(self, url: str) -> str:
        """Add https:// scheme if missing."""
        if not url.startswith(("http://", "https://")):
            return f"https://{url}"
        return url

    async def _template_get(self, ctx: ProviderContext, uri: str) -> HTTPResource:
        """Template function for HTTP GET.

        Args:
            ctx: Provider context.
            uri: URL to fetch (scheme optional, defaults to https://).

        Returns:
            HTTPResource with content and metadata.
        """
        uri = self._normalize_url(uri)
        client = await self._get_client()
        response = await client.get(uri)
        response.raise_for_status()

        # Parse Last-Modified if present
        updated = None
        last_modified = response.headers.get("last-modified")
        if last_modified:
            try:
                updated = parsedate_to_datetime(last_modified)
            except ValueError:
                pass

        return HTTPResource(
            uri=uri,
            content=response.text,
            content_type=response.headers.get("content-type"),
            updated=updated,
        )
