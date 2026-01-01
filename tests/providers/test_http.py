"""Tests for HTTP provider."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from colin.providers.http import HTTPProvider, HTTPResource


class TestHTTPResource:
    """Tests for HTTPResource dataclass."""

    def test_last_updated_returns_updated_when_set(self) -> None:
        """last_updated returns the _last_updated field when set."""
        ts = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        resource = HTTPResource(url="https://example.com", _content="test", _last_updated=ts)

        assert resource.last_updated == ts

    def test_last_updated_returns_now_when_not_set(self) -> None:
        """last_updated returns current time when _last_updated is None."""
        resource = HTTPResource(url="https://example.com", _content="test")

        # Should be very recent
        now = datetime.now(timezone.utc)
        assert (now - resource.last_updated).total_seconds() < 1

    def test_str_returns_content(self) -> None:
        """__str__ returns the content for template use."""
        resource = HTTPResource(
            url="https://example.com/data.json",
            _content='{"key": "value"}',
        )

        assert str(resource) == '{"key": "value"}'

    def test_address_returns_valid_address(self) -> None:
        """address() returns an Address with correct fields."""
        resource = HTTPResource(
            url="https://example.com/data.json",
            _content='{"key": "value"}',
        )

        addr = resource.address()

        assert addr["provider"] == "http"
        assert addr["payload"]["url"] == "https://example.com/data.json"


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


class TestHTTPProviderLoadAddress:
    """Tests for HTTPProvider.load_address()."""

    async def test_load_address_returns_http_resource(self) -> None:
        """load_address() returns HTTPResource with content."""
        provider = HTTPProvider()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "Hello, World!"
        mock_response.headers = {}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.load_address({"url": "https://example.com/test.txt"})

        assert isinstance(result, HTTPResource)
        assert result.content == "Hello, World!"
        assert result.url == "https://example.com/test.txt"
        mock_client.get.assert_called_once_with("https://example.com/test.txt")

    async def test_load_address_raises_file_not_found_on_404(self) -> None:
        """load_address() raises FileNotFoundError on 404."""
        provider = HTTPProvider()

        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        with pytest.raises(FileNotFoundError, match="URL not found"):
            await provider.load_address({"url": "https://example.com/missing.txt"})

    async def test_load_address_raises_on_other_http_errors(self) -> None:
        """load_address() raises HTTPStatusError on non-404 errors."""
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
            await provider.load_address({"url": "https://example.com/error"})


class TestHTTPProviderGetLastUpdated:
    """Tests for HTTPProvider.get_last_updated()."""

    async def test_returns_datetime_from_last_modified_header(self) -> None:
        """get_last_updated() parses Last-Modified header."""
        provider = HTTPProvider()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"last-modified": "Sun, 15 Jan 2024 12:00:00 GMT"}

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.get_last_updated({"url": "https://example.com/file.txt"})

        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    async def test_returns_none_when_no_header(self) -> None:
        """get_last_updated() returns None when header is missing."""
        provider = HTTPProvider()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.get_last_updated({"url": "https://example.com/file.txt"})

        assert result is None

    async def test_returns_none_on_http_error(self) -> None:
        """get_last_updated() returns None on HTTP errors."""
        provider = HTTPProvider()

        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.get_last_updated({"url": "https://example.com/missing.txt"})

        assert result is None

    async def test_returns_none_on_connection_error(self) -> None:
        """get_last_updated() returns None on connection errors."""
        provider = HTTPProvider()

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(side_effect=httpx.ConnectError("Connection failed"))
        provider._client = mock_client

        result = await provider.get_last_updated({"url": "https://example.com/file.txt"})

        assert result is None


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
        assert result.last_updated is not None
        assert result.last_updated.year == 2024


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
