"""S3 provider for reading files from S3-compatible storage.

TODO: Switch to aioboto3 for native async when the boto3 version conflict is resolved.
See: https://github.com/terricain/aioboto3/issues/398
Currently pydantic-ai requires boto3>=1.42 but aioboto3 pins boto3<1.40.62.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from functools import partial
from typing import Any, ClassVar

import boto3
from pydantic import validate_call

from colin.compiler.cache import get_compile_context
from colin.models import Ref
from colin.providers.base import Provider
from colin.resources import Resource


class S3Resource(Resource):
    """Resource returned by S3Provider."""

    def __init__(
        self,
        content: str,
        ref: Ref,
        bucket: str,
        key: str,
        etag: str | None = None,
    ) -> None:
        """Initialize an S3 resource.

        Args:
            content: Object content.
            ref: The Ref for this resource.
            bucket: S3 bucket name.
            key: S3 object key.
            etag: ETag from S3 metadata (used as version).
        """
        super().__init__(content, ref)
        self.bucket = bucket
        self.key = key
        self._etag = etag

    @property
    def version(self) -> str:
        """Use ETag if available, else content hash."""
        if self._etag is not None:
            return self._etag
        return super().version


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
    _connection: str = ""

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

    @validate_call
    async def get(self, path: str, watch: bool = True) -> S3Resource:
        """Fetch S3 object and return S3Resource.

        Template usage: {{ s3.get("bucket/key") }}

        Args:
            path: S3 path in format "bucket/key" or "bucket/path/to/key".
            watch: Whether to track this ref for staleness (default True).

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

        client = self._require_client()
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, partial(client.get_object, Bucket=bucket, Key=key)
        )
        body = response["Body"].read()
        content = body.decode("utf-8")
        etag = response.get("ETag", "").strip('"')

        ref = Ref(
            provider=self.namespace,
            connection=self._connection,
            method="get",
            args={"path": path},
        )

        resource = S3Resource(
            content=content,
            ref=ref,
            bucket=bucket,
            key=key,
            etag=etag or None,
        )

        if watch:
            ctx = get_compile_context()
            if ctx:
                ctx.track(ref, resource.version)

        return resource

    async def get_ref_version(self, ref: Ref) -> str:
        """Get version via HEAD request (no content fetch).

        Args:
            ref: The Ref to check.

        Returns:
            ETag from S3, or content hash if unavailable.
        """
        path = ref.args["path"]
        bucket, key = path.split("/", 1)
        client = self._require_client()
        loop = asyncio.get_event_loop()

        try:
            response = await loop.run_in_executor(
                None, partial(client.head_object, Bucket=bucket, Key=key)
            )
            etag = response.get("ETag", "").strip('"')
            if etag:
                return etag
        except Exception:
            pass

        # Fall back to full fetch
        resource = await self._load_ref(ref)
        return resource.version

    def get_functions(self) -> dict[str, Callable[..., Awaitable[object]]]:
        return {"get": self.get}
