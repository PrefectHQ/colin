"""Tests for S3 provider."""

from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws

from colin.providers.s3 import S3Provider, S3Resource


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

    async def test_get_returns_ref_with_correct_fields(self) -> None:
        """get() returns resource with properly structured Ref."""
        with mock_aws():
            s3_client = boto3.client("s3", region_name="us-east-1")
            s3_client.create_bucket(Bucket="my-bucket")
            s3_client.put_object(Bucket="my-bucket", Key="file.txt", Body=b"Content")

            provider = S3Provider(region="us-east-1")

            async with provider.lifespan():
                result = await provider.get("my-bucket/file.txt")

            ref = result.ref()
            assert ref.provider == "s3"
            assert ref.method == "get"
            assert ref.args == {"path": "my-bucket/file.txt"}

    async def test_get_uses_etag_as_version(self) -> None:
        """get() uses ETag from S3 response as version."""
        with mock_aws():
            s3_client = boto3.client("s3", region_name="us-east-1")
            s3_client.create_bucket(Bucket="my-bucket")
            s3_client.put_object(Bucket="my-bucket", Key="file.txt", Body=b"Content")

            provider = S3Provider(region="us-east-1")

            async with provider.lifespan():
                result = await provider.get("my-bucket/file.txt")

            # Moto generates an ETag, so version should not be content hash
            assert result.version is not None
            assert len(result.version) > 0


class TestS3ProviderGetRefVersion:
    """Tests for S3Provider.get_ref_version()."""

    async def test_get_ref_version_uses_head_request(self) -> None:
        """get_ref_version() uses HEAD request to get ETag."""
        with mock_aws():
            s3_client = boto3.client("s3", region_name="us-east-1")
            s3_client.create_bucket(Bucket="my-bucket")
            s3_client.put_object(Bucket="my-bucket", Key="file.txt", Body=b"Content")

            provider = S3Provider(region="us-east-1")

            async with provider.lifespan():
                result = await provider.get("my-bucket/file.txt")
                ref = result.ref()

                # Get version via get_ref_version
                version = await provider.get_ref_version(ref)

            assert version == result.version


class TestS3ProviderIntegration:
    """Integration tests using moto to mock S3."""

    async def test_get_from_mocked_s3(self) -> None:
        """get() actually reads from mocked S3 bucket."""
        with mock_aws():
            s3_client = boto3.client("s3", region_name="us-east-1")
            s3_client.create_bucket(Bucket="test-bucket")
            s3_client.put_object(Bucket="test-bucket", Key="test-file.txt", Body=b"Hello from S3!")

            provider = S3Provider(region="us-east-1")

            async with provider.lifespan():
                result = await provider.get("test-bucket/test-file.txt")

            assert result.content == "Hello from S3!"

    async def test_get_utf8_content(self) -> None:
        """get() correctly decodes UTF-8 content."""
        with mock_aws():
            test_content = "Hello, 世界! 🌍"
            s3_client = boto3.client("s3", region_name="us-east-1")
            s3_client.create_bucket(Bucket="test-bucket")
            s3_client.put_object(
                Bucket="test-bucket", Key="unicode.txt", Body=test_content.encode("utf-8")
            )

            provider = S3Provider(region="us-east-1")

            async with provider.lifespan():
                result = await provider.get("test-bucket/unicode.txt")

            assert result.content == test_content

    async def test_get_nested_path(self) -> None:
        """get() handles nested S3 paths."""
        with mock_aws():
            s3_client = boto3.client("s3", region_name="us-east-1")
            s3_client.create_bucket(Bucket="my-bucket")
            s3_client.put_object(
                Bucket="my-bucket", Key="path/to/nested/file.txt", Body=b"Nested content"
            )

            provider = S3Provider(region="us-east-1")

            async with provider.lifespan():
                result = await provider.get("my-bucket/path/to/nested/file.txt")

            assert result.content == "Nested content"

    async def test_get_raises_on_missing_object(self) -> None:
        """get() raises error for missing objects."""
        from botocore.exceptions import ClientError

        with mock_aws():
            s3_client = boto3.client("s3", region_name="us-east-1")
            s3_client.create_bucket(Bucket="test-bucket")

            provider = S3Provider(region="us-east-1")

            async with provider.lifespan():
                with pytest.raises(ClientError):
                    await provider.get("test-bucket/missing-file.txt")
