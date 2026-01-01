"""HTTP provider for fetching web resources."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, ClassVar

import httpx

from colin.models import Address
from colin.providers.addressable import Addressable
from colin.providers.base import Provider


@dataclass
class HTTPResource(Addressable):
    """Domain object returned by http.get(). Inherits from Addressable."""

    url: str
    """The URL that was fetched."""

    _content: str
    """The response content."""

    content_type: str | None = None
    """Content-Type header from response."""

    _last_updated: datetime | None = None
    """Last-Modified header from response."""

    _instance: str = field(default="", repr=False)
    """Provider instance name."""

    @property
    def content(self) -> str:
        return self._content

    @property
    def last_updated(self) -> datetime:
        return self._last_updated or datetime.now(timezone.utc)

    def address(self) -> Address:
        return Address(
            provider="http",
            instance=self._instance,
            payload={"url": self.url},
        )


class HTTPProvider(Provider):
    """Provider for fetching HTTP resources.

    Template usage: {{ http.get("example.com/data.json") }}
    """

    namespace: ClassVar[str] = "http"

    timeout: float = 30.0
    """Request timeout in seconds."""

    _client: httpx.AsyncClient | None = None
    _instance: str = ""

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        """Manage HTTP client lifecycle."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            self._client = client
            yield
        self._client = None

    def _require_client(self) -> httpx.AsyncClient:
        """Get client, raising if not initialized."""
        if self._client is None:
            raise RuntimeError("HTTPProvider not initialized - use within lifespan context")
        return self._client

    async def load_address(self, payload: dict[str, Any]) -> HTTPResource:
        """Load content from address payload.

        Args:
            payload: Dict with 'url' key.

        Returns:
            HTTPResource with content and metadata.
        """
        url = payload["url"]
        return await self._fetch(url)

    async def _fetch(self, url: str) -> HTTPResource:
        """Fetch URL and return HTTPResource."""
        client = self._require_client()
        response = await client.get(url)

        if response.status_code == 404:
            raise FileNotFoundError(f"URL not found: {url}")

        response.raise_for_status()

        updated = None
        last_modified = response.headers.get("last-modified")
        if last_modified:
            try:
                updated = parsedate_to_datetime(last_modified)
            except ValueError:
                pass

        return HTTPResource(
            url=url,
            _content=response.text,
            content_type=response.headers.get("content-type"),
            _last_updated=updated,
            _instance=self._instance,
        )

    async def get_last_updated(self, payload: dict[str, Any]) -> datetime | None:
        """Get last modified time via HEAD request."""
        url = payload["url"]
        try:
            client = self._require_client()
            response = await client.head(url)

            if response.status_code >= 400:
                return None

            last_modified = response.headers.get("last-modified")
            if last_modified:
                return parsedate_to_datetime(last_modified)

            return None
        except httpx.HTTPError:
            return None

    def get_functions(self) -> dict[str, Callable[..., Awaitable[object]]]:
        return {"get": self.get}

    def _normalize_url(self, url: str) -> str:
        """Add https:// scheme if missing."""
        if not url.startswith(("http://", "https://")):
            return f"https://{url}"
        return url

    async def get(self, url: str) -> HTTPResource:
        """Fetch URL and return HTTPResource.

        Template usage: {{ http.get("example.com/data.json") }}

        Args:
            url: URL to fetch (scheme optional, defaults to https://).

        Returns:
            HTTPResource with content and metadata.
        """
        return await self._fetch(self._normalize_url(url))
