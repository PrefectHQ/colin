"""S3 provider for reading files from S3-compatible storage.

TODO: Switch to aioboto3 for native async when the boto3 version conflict is resolved.
See: https://github.com/terricain/aioboto3/issues/398
Currently pydantic-ai requires boto3>=1.42 but aioboto3 pins boto3<1.40.62.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from functools import partial
from typing import Any, ClassVar

import boto3

from colin.providers.base import Provider


class S3Provider(Provider):
    """Provider for s3:// URIs."""

    namespace: ClassVar[str] = "s3"
    schemes: list[str] = ["s3"]

    region: str | None = None
    """AWS region (e.g., 'us-west-2', 'eu-west-1')."""

    profile: str | None = None
    """AWS profile name from ~/.aws/credentials."""

    endpoint_url: str | None = None
    """Custom endpoint for S3-compatible services (MinIO, LocalStack, etc.)."""

    _client: Any = None

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        session = boto3.Session(
            region_name=self.region,
            profile_name=self.profile,
        )
        self._client = session.client("s3", endpoint_url=self.endpoint_url)
        try:
            yield
        finally:
            if self._client:
                self._client.close()
            self._client = None

    def _require_client(self) -> Any:
        if self._client is None:
            raise RuntimeError("S3Provider not initialized - use within lifespan context")
        return self._client

    async def read(self, uri: str) -> str:
        """Read content from S3 object.

        Args:
            uri: Full S3 URI (e.g., 's3://bucket/path/to/key').

        Returns:
            Object content as string.

        Raises:
            FileNotFoundError: If object doesn't exist.
            RuntimeError: If called outside lifespan context.
        """
        bucket, key = self._parse_uri(uri)
        client = self._require_client()
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, partial(client.get_object, Bucket=bucket, Key=key)
        )
        body = response["Body"].read()
        return body.decode("utf-8")

    async def get_last_updated(self, uri: str) -> datetime | None:
        """Get last modified time for S3 object.

        Args:
            uri: Full S3 URI.

        Returns:
            LastModified datetime, or None if not available.

        Raises:
            RuntimeError: If called outside lifespan context.
        """
        bucket, key = self._parse_uri(uri)
        client = self._require_client()
        loop = asyncio.get_event_loop()
        try:
            response = await loop.run_in_executor(
                None, partial(client.head_object, Bucket=bucket, Key=key)
            )
            return response.get("LastModified")
        except Exception:
            return None

    def _parse_uri(self, uri: str) -> tuple[str, str]:
        """Parse S3 URI into bucket and key.

        Args:
            uri: S3 URI (e.g., 's3://bucket/path/to/key').

        Returns:
            Tuple of (bucket, key).

        Raises:
            ValueError: If URI format is invalid.
        """
        if not uri.startswith("s3://"):
            raise ValueError(f"Invalid S3 URI: {uri}. Must start with 's3://'")

        path = uri.split("://", 1)[1]
        if "/" not in path:
            raise ValueError(f"Invalid S3 URI: {uri}. Must include bucket and key")

        bucket, key = path.split("/", 1)
        if not bucket:
            raise ValueError(f"Invalid S3 URI: {uri}. Bucket name cannot be empty")

        return bucket, key
