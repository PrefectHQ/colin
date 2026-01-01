"""Tests for S3 provider."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws

from colin.providers.s3 import S3Provider


class TestS3Provider:
    """Tests for S3Provider."""

    def test_namespace_is_s3(self) -> None:
        """Provider namespace is 's3'."""
        provider = S3Provider()

        assert provider.namespace == "s3"

    def test_from_config_creates_provider(self) -> None:
        """from_config() creates provider with validated config."""
        provider = S3Provider.from_config(None, {"region": "us-west-2"})

        assert isinstance(provider, S3Provider)
        assert provider.region == "us-west-2"

    def test_from_config_with_all_options(self) -> None:
        """from_config() accepts region, profile, endpoint_url."""
        provider = S3Provider.from_config(
            None,
            {
                "region": "us-east-1",
                "profile": "my-profile",
                "endpoint_url": "http://localhost:9000",
            },
        )

        assert provider.region == "us-east-1"
        assert provider.profile == "my-profile"
        assert provider.endpoint_url == "http://localhost:9000"

    def test_from_config_with_empty_dict(self) -> None:
        """from_config() accepts empty config dict."""
        provider = S3Provider.from_config(None, {})

        assert isinstance(provider, S3Provider)
        assert provider.region is None


class TestS3ProviderLoadAddress:
    """Tests for S3Provider.load_address()."""

    async def test_load_address_returns_s3_resource(self) -> None:
        """load_address() returns S3Resource with content."""
        with mock_aws():
            # Set up mocked S3 with sync boto3
            s3_client = boto3.client("s3", region_name="us-east-1")
            s3_client.create_bucket(Bucket="my-bucket")
            s3_client.put_object(Bucket="my-bucket", Key="file.txt", Body=b"Hello, World!")

            provider = S3Provider(region="us-east-1")

            async with provider.lifespan():
                result = await provider.load_address({"bucket": "my-bucket", "key": "file.txt"})

            from colin.providers.s3 import S3Resource

            assert isinstance(result, S3Resource)
            assert result.content == "Hello, World!"
            assert result.bucket == "my-bucket"
            assert result.key == "file.txt"

    async def test_load_address_decodes_utf8(self) -> None:
        """load_address() decodes content as UTF-8."""
        with mock_aws():
            test_content = "Hello, 世界!"
            s3_client = boto3.client("s3", region_name="us-east-1")
            s3_client.create_bucket(Bucket="bucket")
            s3_client.put_object(Bucket="bucket", Key="file.txt", Body=test_content.encode("utf-8"))

            provider = S3Provider(region="us-east-1")

            async with provider.lifespan():
                result = await provider.load_address({"bucket": "bucket", "key": "file.txt"})

            assert result.content == test_content

    async def test_load_address_raises_when_not_initialized(self) -> None:
        """load_address() raises RuntimeError when called outside lifespan."""
        provider = S3Provider()

        with pytest.raises(RuntimeError, match="not initialized"):
            await provider.load_address({"bucket": "bucket", "key": "file.txt"})


class TestS3ProviderGetLastUpdated:
    """Tests for S3Provider.get_last_updated()."""

    async def test_returns_last_modified(self) -> None:
        """get_last_updated() returns LastModified datetime."""
        with mock_aws():
            s3_client = boto3.client("s3", region_name="us-east-1")
            s3_client.create_bucket(Bucket="my-bucket")
            s3_client.put_object(Bucket="my-bucket", Key="file.txt", Body=b"Content")

            provider = S3Provider(region="us-east-1")

            async with provider.lifespan():
                result = await provider.get_last_updated({"bucket": "my-bucket", "key": "file.txt"})

            assert result is not None
            assert isinstance(result, datetime)

    async def test_returns_none_when_missing(self) -> None:
        """get_last_updated() returns None for missing objects."""
        with mock_aws():
            s3_client = boto3.client("s3", region_name="us-east-1")
            s3_client.create_bucket(Bucket="bucket")

            provider = S3Provider(region="us-east-1")

            async with provider.lifespan():
                result = await provider.get_last_updated({"bucket": "bucket", "key": "missing.txt"})

            assert result is None

    async def test_raises_when_not_initialized(self) -> None:
        """get_last_updated() raises RuntimeError when called outside lifespan."""
        provider = S3Provider()

        with pytest.raises(RuntimeError, match="not initialized"):
            await provider.get_last_updated({"bucket": "bucket", "key": "file.txt"})


class TestS3ProviderLifespan:
    """Tests for S3Provider lifespan lifecycle."""

    @patch("colin.providers.s3.boto3")
    async def test_lifespan_creates_and_clears_client(self, mock_boto3: MagicMock) -> None:
        """lifespan() creates client on enter and clears on exit."""
        provider = S3Provider(region="us-west-2", profile="my-profile")

        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_boto3.Session.return_value = mock_session

        assert provider._client is None

        async with provider.lifespan():
            assert provider._client is not None
            mock_session.client.assert_called_once_with("s3", endpoint_url=None)

        assert provider._client is None
        mock_client.close.assert_called_once()

    @patch("colin.providers.s3.boto3")
    async def test_lifespan_uses_endpoint_url(self, mock_boto3: MagicMock) -> None:
        """lifespan() passes endpoint_url to client."""
        provider = S3Provider(endpoint_url="http://localhost:9000")

        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_boto3.Session.return_value = mock_session

        async with provider.lifespan():
            mock_session.client.assert_called_once_with("s3", endpoint_url="http://localhost:9000")

    @patch("colin.providers.s3.boto3")
    async def test_lifespan_uses_region_and_profile(self, mock_boto3: MagicMock) -> None:
        """lifespan() passes region and profile to Session."""
        provider = S3Provider(region="us-east-1", profile="test-profile")

        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_boto3.Session.return_value = mock_session

        async with provider.lifespan():
            mock_boto3.Session.assert_called_once_with(
                region_name="us-east-1", profile_name="test-profile"
            )


class TestS3ProviderIntegration:
    """Integration tests using moto to mock S3."""

    async def test_load_address_from_mocked_s3(self) -> None:
        """load_address() actually reads from mocked S3 bucket."""
        with mock_aws():
            s3_client = boto3.client("s3", region_name="us-east-1")
            s3_client.create_bucket(Bucket="test-bucket")
            s3_client.put_object(Bucket="test-bucket", Key="test-file.txt", Body=b"Hello from S3!")

            provider = S3Provider(region="us-east-1")

            async with provider.lifespan():
                result = await provider.load_address(
                    {"bucket": "test-bucket", "key": "test-file.txt"}
                )

            assert result.content == "Hello from S3!"

    async def test_load_address_utf8_content(self) -> None:
        """load_address() correctly decodes UTF-8 content."""
        with mock_aws():
            test_content = "Hello, 世界! 🌍"
            s3_client = boto3.client("s3", region_name="us-east-1")
            s3_client.create_bucket(Bucket="test-bucket")
            s3_client.put_object(
                Bucket="test-bucket", Key="unicode.txt", Body=test_content.encode("utf-8")
            )

            provider = S3Provider(region="us-east-1")

            async with provider.lifespan():
                result = await provider.load_address(
                    {"bucket": "test-bucket", "key": "unicode.txt"}
                )

            assert result.content == test_content

    async def test_load_address_nested_path(self) -> None:
        """load_address() handles nested S3 paths."""
        with mock_aws():
            s3_client = boto3.client("s3", region_name="us-east-1")
            s3_client.create_bucket(Bucket="my-bucket")
            s3_client.put_object(
                Bucket="my-bucket", Key="path/to/nested/file.txt", Body=b"Nested content"
            )

            provider = S3Provider(region="us-east-1")

            async with provider.lifespan():
                result = await provider.load_address(
                    {"bucket": "my-bucket", "key": "path/to/nested/file.txt"}
                )

            assert result.content == "Nested content"

    async def test_load_address_raises_on_missing_object(self) -> None:
        """load_address() raises error for missing objects."""
        from botocore.exceptions import ClientError

        with mock_aws():
            s3_client = boto3.client("s3", region_name="us-east-1")
            s3_client.create_bucket(Bucket="test-bucket")

            provider = S3Provider(region="us-east-1")

            async with provider.lifespan():
                with pytest.raises(ClientError):
                    await provider.load_address(
                        {"bucket": "test-bucket", "key": "missing-file.txt"}
                    )

    async def test_get_last_updated_returns_timestamp(self) -> None:
        """get_last_updated() returns LastModified timestamp."""
        with mock_aws():
            s3_client = boto3.client("s3", region_name="us-east-1")
            s3_client.create_bucket(Bucket="test-bucket")
            s3_client.put_object(Bucket="test-bucket", Key="file.txt", Body=b"Content")

            provider = S3Provider(region="us-east-1")

            async with provider.lifespan():
                last_updated = await provider.get_last_updated(
                    {"bucket": "test-bucket", "key": "file.txt"}
                )

            assert last_updated is not None
            assert isinstance(last_updated, datetime)

    async def test_get_last_updated_returns_none_for_missing(self) -> None:
        """get_last_updated() returns None for missing objects."""
        with mock_aws():
            s3_client = boto3.client("s3", region_name="us-east-1")
            s3_client.create_bucket(Bucket="test-bucket")

            provider = S3Provider(region="us-east-1")

            async with provider.lifespan():
                last_updated = await provider.get_last_updated(
                    {"bucket": "test-bucket", "key": "missing.txt"}
                )

            assert last_updated is None


class TestS3ProviderGet:
    """Tests for S3Provider.get() template function."""

    async def test_get_returns_s3_resource(self) -> None:
        """get() returns S3Resource with content."""
        with mock_aws():
            s3_client = boto3.client("s3", region_name="us-east-1")
            s3_client.create_bucket(Bucket="my-bucket")
            s3_client.put_object(Bucket="my-bucket", Key="file.txt", Body=b"Hello!")

            provider = S3Provider(region="us-east-1")

            async with provider.lifespan():
                result = await provider.get("my-bucket/file.txt")

            from colin.providers.s3 import S3Resource

            assert isinstance(result, S3Resource)
            assert result.content == "Hello!"
            assert result.bucket == "my-bucket"
            assert result.key == "file.txt"

    async def test_get_handles_nested_path(self) -> None:
        """get() handles nested paths correctly."""
        with mock_aws():
            s3_client = boto3.client("s3", region_name="us-east-1")
            s3_client.create_bucket(Bucket="bucket")
            s3_client.put_object(Bucket="bucket", Key="path/to/file.txt", Body=b"Nested")

            provider = S3Provider(region="us-east-1")

            async with provider.lifespan():
                result = await provider.get("bucket/path/to/file.txt")

            assert result.content == "Nested"
            assert result.bucket == "bucket"
            assert result.key == "path/to/file.txt"

    async def test_get_raises_on_invalid_path(self) -> None:
        """get() raises ValueError for path without slash."""
        provider = S3Provider()

        with pytest.raises(ValueError, match="Invalid S3 path"):
            await provider.get("nobucket")

    async def test_get_raises_on_empty_bucket(self) -> None:
        """get() raises ValueError when bucket name is empty."""
        provider = S3Provider()

        with pytest.raises(ValueError, match="Bucket name cannot be empty"):
            await provider.get("/path/to/file.txt")
