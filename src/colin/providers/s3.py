"""S3 provider for reading files from S3-compatible storage.

TODO: Switch to aioboto3 for native async when the boto3 version conflict is resolved.
See: https://github.com/terricain/aioboto3/issues/398
Currently pydantic-ai requires boto3>=1.42 but aioboto3 pins boto3<1.40.62.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial
from typing import Any, ClassVar

import boto3

from colin.models import Address
from colin.providers.addressable import Addressable
from colin.providers.base import Provider


@dataclass
class S3Resource(Addressable):
    """Domain object returned by S3Provider. Inherits from Addressable."""

    bucket: str
    """S3 bucket name."""

    key: str
    """S3 object key."""

    _content: str
    """Object content."""

    _last_updated: datetime | None = None
    """LastModified from S3 metadata."""

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
            provider="s3",
            instance=self._instance,
            payload={"bucket": self.bucket, "key": self.key},
        )


class S3Provider(Provider):
    """Provider for reading files from S3-compatible storage.

    Template usage: {{ s3.get("bucket/key") }}
    """

    namespace: ClassVar[str] = "s3"

    region: str | None = None
    """AWS region (e.g., 'us-west-2', 'eu-west-1')."""

    profile: str | None = None
    """AWS profile name from ~/.aws/credentials."""

    endpoint_url: str | None = None
    """Custom endpoint for S3-compatible services (MinIO, LocalStack, etc.)."""

    _client: Any = None
    _instance: str = ""

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

    async def load_address(self, payload: dict[str, Any]) -> S3Resource:
        """Load content from address payload.

        Args:
            payload: Dict with 'bucket' and 'key'.

        Returns:
            S3Resource with content and metadata.
        """
        bucket = payload["bucket"]
        key = payload["key"]
        return await self._fetch(bucket, key)

    async def _fetch(self, bucket: str, key: str) -> S3Resource:
        """Fetch S3 object and return S3Resource."""
        client = self._require_client()
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, partial(client.get_object, Bucket=bucket, Key=key)
        )
        body = response["Body"].read()
        content = body.decode("utf-8")
        last_modified = response.get("LastModified")

        return S3Resource(
            bucket=bucket,
            key=key,
            _content=content,
            _last_updated=last_modified,
            _instance=self._instance,
        )

    async def get_last_updated(self, payload: dict[str, Any]) -> datetime | None:
        """Get last modified time for S3 object.

        Args:
            payload: Dict with 'bucket' and 'key'.

        Returns:
            LastModified datetime, or None if not available.

        Raises:
            RuntimeError: If called outside lifespan context.
        """
        bucket = payload["bucket"]
        key = payload["key"]
        client = self._require_client()
        loop = asyncio.get_event_loop()
        try:
            response = await loop.run_in_executor(
                None, partial(client.head_object, Bucket=bucket, Key=key)
            )
            return response.get("LastModified")
        except Exception:
            return None

    def get_functions(self) -> dict[str, Callable[..., Awaitable[object]]]:
        return {"get": self.get}

    async def get(self, path: str) -> S3Resource:
        """Fetch S3 object and return S3Resource.

        Template usage: {{ s3.get("bucket/key") }}

        Args:
            path: S3 path in format "bucket/key" or "bucket/path/to/key".

        Returns:
            S3Resource with content and metadata.

        Raises:
            ValueError: If path format is invalid.
        """
        if "/" not in path:
            raise ValueError(f"Invalid S3 path: {path}. Must be 'bucket/key' format")

        bucket, key = path.split("/", 1)
        if not bucket:
            raise ValueError(f"Invalid S3 path: {path}. Bucket name cannot be empty")

        return await self._fetch(bucket, key)
