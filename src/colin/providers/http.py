"""HTTP provider for fetching web resources."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import ClassVar

import httpx
from pydantic import validate_call

from colin.compiler.cache import get_compile_context
from colin.models import Ref
from colin.providers.base import Provider
from colin.resources import Resource


class HTTPResource(Resource):
    """Resource returned by HTTPProvider."""

    def __init__(
        self,
        content: str,
        ref: Ref,
        url: str,
        content_type: str | None = None,
        last_modified: datetime | None = None,
    ) -> None:
        """Initialize an HTTP resource.

        Args:
            content: Response body content.
            ref: The Ref for this resource.
            url: The URL that was fetched.
            content_type: Content-Type header from response.
            last_modified: Last-Modified header from response.
        """
        super().__init__(content, ref)
        self.url = url
        self.content_type = content_type
        self._last_modified = last_modified

    @property
    def version(self) -> str:
        """Use Last-Modified if available, else content hash."""
        if self._last_modified is not None:
            return self._last_modified.isoformat()
        return super().version


class HTTPProvider(Provider):
    """Provider for fetching HTTP resources.

    Template usage: {{ colin.http.get("example.com/data.json") }}

    Note: HTTP resources default to watch=False since web content is volatile.
    """

    namespace: ClassVar[str] = "http"

    timeout: float = 30.0
    """Request timeout in seconds."""

    _client: httpx.AsyncClient | None = None
    _connection: str = ""

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

    def _normalize_url(self, url: str) -> str:
        """Add https:// scheme if missing."""
        if not url.startswith(("http://", "https://")):
            return f"https://{url}"
        return url

    @validate_call
    async def get(self, url: str, watch: bool = False) -> HTTPResource:
        """Fetch URL and return HTTPResource.

        Template usage: {{ colin.http.get("example.com/data.json") }}

        Args:
            url: URL to fetch (scheme optional, defaults to https://).
            watch: Whether to track this ref for staleness (default False for HTTP).

        Returns:
            HTTPResource with content and metadata.
        """
        normalized_url = self._normalize_url(url)
        client = self._require_client()
        response = await client.get(normalized_url)

        if response.status_code == 404:
            raise FileNotFoundError(f"URL not found: {normalized_url}")

        response.raise_for_status()

        last_modified = None
        last_modified_header = response.headers.get("last-modified")
        if last_modified_header:
            try:
                last_modified = parsedate_to_datetime(last_modified_header)
            except ValueError:
                pass

        ref = Ref(
            provider=self.namespace,
            connection=self._connection,
            method="get",
            args={"url": normalized_url},
        )

        resource = HTTPResource(
            content=response.text,
            ref=ref,
            url=normalized_url,
            content_type=response.headers.get("content-type"),
            last_modified=last_modified,
        )

        if watch:
            ctx = get_compile_context()
            if ctx:
                ctx.track(ref, resource.version)

        return resource

    async def get_ref_version(self, ref: Ref) -> str:
        """Get version via HEAD request if possible.

        Args:
            ref: The Ref to check.

        Returns:
            Last-Modified header as ISO string, or content hash.
        """
        # URL is already normalized in the Ref
        normalized_url = ref.args["url"]

        try:
            client = self._require_client()
            response = await client.head(normalized_url)

            if response.status_code >= 400:
                # Fall back to full fetch
                resource = await self._load_ref(ref)
                return resource.version

            last_modified = response.headers.get("last-modified")
            if last_modified:
                return parsedate_to_datetime(last_modified).isoformat()

            # No Last-Modified header, need full fetch for content hash
            resource = await self._load_ref(ref)
            return resource.version
        except httpx.HTTPError:
            # Fall back to full fetch
            resource = await self._load_ref(ref)
            return resource.version

    def get_functions(self) -> dict[str, Callable[..., Awaitable[object]]]:
        return {"get": self.get}
