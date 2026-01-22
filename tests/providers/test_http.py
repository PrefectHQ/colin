"""Tests for HTTP provider."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from colin.models import Ref
from colin.providers.http import HTTPProvider, HTTPResource


class TestHTTPResource:
    """Tests for HTTPResource class."""

    def test_version_uses_last_modified_when_set(self) -> None:
        """version returns ISO datetime when last_modified is set."""
        ts = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        ref = Ref(provider="http", connection="", method="get", args={"url": "example.com"})
        resource = HTTPResource(
            content="test",
            ref=ref,
            url="https://example.com",
            last_modified=ts,
        )

        assert resource.version == ts.isoformat()

    def test_version_uses_content_hash_when_no_last_modified(self) -> None:
        """version returns content hash when last_modified is None."""
        ref = Ref(provider="http", connection="", method="get", args={"url": "example.com"})
        resource = HTTPResource(
            content="test",
            ref=ref,
            url="https://example.com",
        )

        # Should be a 16-character hex hash
        assert len(resource.version) == 16
        assert all(c in "0123456789abcdef" for c in resource.version)

    def test_str_returns_descriptive_string(self) -> None:
        """__str__ returns a descriptive string, not content."""
        ref = Ref(
            provider="http", connection="", method="get", args={"url": "example.com/data.json"}
        )
        resource = HTTPResource(
            content='{"key": "value"}',
            ref=ref,
            url="https://example.com/data.json",
        )

        result = str(resource)
        assert result.startswith("<HTTPResource(")
        assert result.endswith(")>")
        assert resource.content == '{"key": "value"}'

    def test_ref_returns_valid_ref(self) -> None:
        """ref() returns a Ref with correct fields."""
        ref = Ref(
            provider="http", connection="", method="get", args={"url": "example.com/data.json"}
        )
        resource = HTTPResource(
            content='{"key": "value"}',
            ref=ref,
            url="https://example.com/data.json",
        )

        result = resource.ref()

        assert result.provider == "http"
        assert result.method == "get"
        assert result.args["url"] == "example.com/data.json"


class TestHTTPProvider:
    """Tests for HTTPProvider."""

    def test_namespace_is_http(self) -> None:
        """Namespace is 'http'."""
        provider = HTTPProvider()

        assert provider.namespace == "http"

    def test_custom_timeout(self) -> None:
        """Custom timeout is accepted."""
        provider = HTTPProvider(timeout=60.0)

        assert provider.timeout == 60.0


class TestHTTPProviderGet:
    """Tests for HTTPProvider.get() template function."""

    async def test_returns_http_resource(self) -> None:
        """get() returns HTTPResource with content."""
        provider = HTTPProvider()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"data": true}'
        mock_response.headers = {
            "content-type": "application/json",
            "last-modified": "Sun, 15 Jan 2024 12:00:00 GMT",
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.get("https://api.example.com/data")

        assert isinstance(result, HTTPResource)
        assert result.url == "https://api.example.com/data"
        assert result.content == '{"data": true}'
        assert result.content_type == "application/json"
        # Last modified should be parsed
        assert result._last_modified is not None
        assert result._last_modified.year == 2024

    async def test_get_raises_file_not_found_on_404(self) -> None:
        """get() raises FileNotFoundError on 404."""
        provider = HTTPProvider()

        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        with pytest.raises(FileNotFoundError, match="URL not found"):
            await provider.get("https://example.com/missing.txt")

    async def test_get_raises_on_other_http_errors(self) -> None:
        """get() raises HTTPStatusError on non-404 errors."""
        provider = HTTPProvider()

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "Server Error", request=MagicMock(), response=mock_response
            )
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        with pytest.raises(httpx.HTTPStatusError):
            await provider.get("https://example.com/error")

    async def test_get_returns_ref_with_normalized_url(self) -> None:
        """get() returns Ref with normalized URL (scheme added)."""
        provider = HTTPProvider()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "content"
        mock_response.headers = {}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.get("example.com/data")

        ref = result.ref()
        assert ref.args["url"] == "https://example.com/data"


class TestHTTPProviderGetRefVersion:
    """Tests for HTTPProvider.get_ref_version()."""

    async def test_returns_last_modified_from_head_request(self) -> None:
        """get_ref_version() parses Last-Modified header from HEAD request."""
        provider = HTTPProvider()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"last-modified": "Sun, 15 Jan 2024 12:00:00 GMT"}

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        ref = Ref(
            provider="http", connection="", method="get", args={"url": "example.com/file.txt"}
        )
        result = await provider.get_ref_version(ref)

        expected = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc).isoformat()
        assert result == expected

    async def test_falls_back_to_full_fetch_when_no_header(self) -> None:
        """get_ref_version() falls back to full fetch when no Last-Modified header."""
        provider = HTTPProvider()

        # HEAD response without Last-Modified
        mock_head_response = MagicMock()
        mock_head_response.status_code = 200
        mock_head_response.headers = {}

        # GET response for full fetch
        mock_get_response = MagicMock()
        mock_get_response.status_code = 200
        mock_get_response.text = "content"
        mock_get_response.headers = {}
        mock_get_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=mock_head_response)
        mock_client.get = AsyncMock(return_value=mock_get_response)
        provider._client = mock_client

        ref = Ref(
            provider="http", connection="", method="get", args={"url": "example.com/file.txt"}
        )
        result = await provider.get_ref_version(ref)

        # Should be content hash (16 hex chars)
        assert len(result) == 16


class TestHTTPProviderNormalizeUrl:
    """Tests for URL normalization."""

    def test_adds_https_to_bare_domain(self) -> None:
        """Adds https:// to bare domain."""
        provider = HTTPProvider()

        assert provider._normalize_url("example.com") == "https://example.com"

    def test_adds_https_to_domain_with_path(self) -> None:
        """Adds https:// to domain with path."""
        provider = HTTPProvider()

        assert provider._normalize_url("example.com/api/data") == "https://example.com/api/data"

    def test_preserves_existing_https(self) -> None:
        """Preserves existing https:// scheme."""
        provider = HTTPProvider()

        assert provider._normalize_url("https://example.com") == "https://example.com"

    def test_preserves_existing_http(self) -> None:
        """Preserves existing http:// scheme."""
        provider = HTTPProvider()

        assert provider._normalize_url("http://example.com") == "http://example.com"


class TestHTTPProviderLifecycle:
    """Tests for HTTPProvider lifespan lifecycle."""

    async def test_lifespan_creates_and_clears_client(self) -> None:
        """lifespan() creates client on enter and clears on exit."""
        provider = HTTPProvider()

        assert provider._client is None

        async with provider.lifespan():
            assert provider._client is not None
            assert isinstance(provider._client, httpx.AsyncClient)

        assert provider._client is None

    async def test_lifespan_uses_configured_timeout(self) -> None:
        """lifespan() creates client with configured timeout."""
        provider = HTTPProvider(timeout=60.0)

        async with provider.lifespan():
            assert provider._client is not None
            # httpx.AsyncClient stores timeout as Timeout object
            assert provider._client.timeout.connect == 60.0
