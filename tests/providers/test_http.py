"""Tests for HTTP provider."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from colin.providers.http import HTTPProvider, HTTPResource


class TestHTTPResource:
    """Tests for HTTPResource dataclass."""

    def test_last_updated_returns_updated_when_set(self) -> None:
        """last_updated returns the updated field when set."""
        ts = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        resource = HTTPResource(uri="https://example.com", content="test", updated=ts)

        assert resource.last_updated == ts

    def test_last_updated_returns_now_when_not_set(self) -> None:
        """last_updated returns current time when updated is None."""
        resource = HTTPResource(uri="https://example.com", content="test")

        # Should be very recent
        now = datetime.now(timezone.utc)
        assert (now - resource.last_updated).total_seconds() < 1

    def test_to_ref_result_creates_valid_result(self) -> None:
        """to_ref_result creates a RefResult with correct fields."""
        ts = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        resource = HTTPResource(
            uri="https://example.com/data.json",
            content='{"key": "value"}',
            content_type="application/json",
            updated=ts,
        )

        result = resource.to_ref_result()

        assert result.name == "data.json"
        assert result.content == '{"key": "value"}'
        assert result.uri == "https://example.com/data.json"
        assert result.updated == ts
        assert result.source is resource

    def test_to_ref_result_uses_uri_as_name_when_no_path(self) -> None:
        """to_ref_result uses full URI as name when path is empty."""
        resource = HTTPResource(uri="https://example.com/", content="test")

        result = resource.to_ref_result()

        # Empty string after split, so falls back to URI
        assert result.name == "https://example.com/"


class TestHTTPProvider:
    """Tests for HTTPProvider."""

    def test_schemes_includes_http_and_https(self) -> None:
        """Provider handles both http and https schemes."""
        provider = HTTPProvider()

        assert provider.schemes == ["http", "https"]

    def test_namespace_defaults_to_http(self) -> None:
        """Namespace defaults to first scheme (http)."""
        provider = HTTPProvider()

        assert provider.namespace == "http"

    def test_custom_timeout(self) -> None:
        """Custom timeout is accepted."""
        provider = HTTPProvider(timeout=60.0)

        assert provider._timeout == 60.0


class TestHTTPProviderRead:
    """Tests for HTTPProvider.read()."""

    async def test_read_returns_response_text(self) -> None:
        """read() returns response body as text."""
        provider = HTTPProvider()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "Hello, World!"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(provider, "_get_client", return_value=mock_client):
            result = await provider.read("https://example.com/test.txt")

        assert result == "Hello, World!"
        mock_client.get.assert_called_once_with("https://example.com/test.txt")

    async def test_read_raises_file_not_found_on_404(self) -> None:
        """read() raises FileNotFoundError on 404."""
        provider = HTTPProvider()

        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(provider, "_get_client", return_value=mock_client):
            with pytest.raises(FileNotFoundError, match="URL not found"):
                await provider.read("https://example.com/missing.txt")

    async def test_read_raises_on_other_http_errors(self) -> None:
        """read() raises HTTPStatusError on non-404 errors."""
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

        with patch.object(provider, "_get_client", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await provider.read("https://example.com/error")


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

        with patch.object(provider, "_get_client", return_value=mock_client):
            result = await provider.get_last_updated("https://example.com/file.txt")

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

        with patch.object(provider, "_get_client", return_value=mock_client):
            result = await provider.get_last_updated("https://example.com/file.txt")

        assert result is None

    async def test_returns_none_on_http_error(self) -> None:
        """get_last_updated() returns None on HTTP errors."""
        provider = HTTPProvider()

        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=mock_response)

        with patch.object(provider, "_get_client", return_value=mock_client):
            result = await provider.get_last_updated("https://example.com/missing.txt")

        assert result is None

    async def test_returns_none_on_connection_error(self) -> None:
        """get_last_updated() returns None on connection errors."""
        provider = HTTPProvider()

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(side_effect=httpx.ConnectError("Connection failed"))

        with patch.object(provider, "_get_client", return_value=mock_client):
            result = await provider.get_last_updated("https://example.com/file.txt")

        assert result is None


class TestHTTPProviderTemplateGet:
    """Tests for HTTPProvider._template_get()."""

    async def test_returns_http_resource(self) -> None:
        """_template_get() returns HTTPResource with content."""
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

        mock_ctx = MagicMock()

        with patch.object(provider, "_get_client", return_value=mock_client):
            result = await provider._template_get(mock_ctx, "https://api.example.com/data")

        assert isinstance(result, HTTPResource)
        assert result.uri == "https://api.example.com/data"
        assert result.content == '{"data": true}'
        assert result.content_type == "application/json"
        assert result.updated is not None
        assert result.updated.year == 2024


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
    """Tests for HTTPProvider client lifecycle."""

    async def test_close_closes_client(self) -> None:
        """close() properly closes the HTTP client."""
        provider = HTTPProvider()

        mock_client = AsyncMock()
        mock_client.aclose = AsyncMock()
        provider._client = mock_client

        await provider.close()

        mock_client.aclose.assert_called_once()
        assert provider._client is None

    async def test_close_is_safe_when_no_client(self) -> None:
        """close() is safe to call when no client exists."""
        provider = HTTPProvider()

        # Should not raise
        await provider.close()
