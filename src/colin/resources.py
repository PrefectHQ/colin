"""Resource base class for objects returned by provider functions."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from colin.models import Ref


class Resource:
    """Base class for objects returned by provider functions.

    Resources are containers for content fetched from external sources.
    They hold:
    - The content string
    - A Ref (passed in by the provider, not created by the Resource)
    - A version string for staleness detection

    The Provider creates the Ref and passes it to the Resource constructor.
    This keeps Resources simple and decouples them from provider API details.

    Example:
        class S3Resource(Resource):
            def __init__(self, content: str, ref: Ref, etag: str) -> None:
                super().__init__(content, ref)
                self._etag = etag

            @property
            def version(self) -> str:
                return self._etag  # Use ETag instead of content hash

        # Provider creates both Ref and Resource:
        ref = Ref(provider="s3", connection="", method="get", args={"path": path})
        resource = S3Resource(content=data, ref=ref, etag=response["ETag"])
    """

    def __init__(self, content: str, ref: Ref) -> None:
        """Initialize the resource.

        Args:
            content: The resource content string.
            ref: The Ref for re-fetching this resource (created by provider).
        """
        self._content = content
        self._ref = ref

    @property
    def content(self) -> str:
        """The content of this resource."""
        return self._content

    def ref(self) -> Ref:
        """Return the Ref this resource was given.

        The Ref contains the provider, connection, method, and args
        needed to re-fetch this resource.
        """
        return self._ref

    @property
    def version(self) -> str:
        """Version string for staleness detection.

        By default, returns a hash of the content. Override for:
        - Efficiency: use ETag, mtime, or other metadata
        - Semantics: exclude volatile fields from the hash

        Returns:
            A string that changes when the resource content changes.
        """
        return hashlib.sha256(self._content.encode()).hexdigest()[:16]

    def __str__(self) -> str:
        """Return a descriptive string, not content.

        To render content in templates, use .content explicitly:
            {{ resource.content }}

        This prevents accidental content dumping and makes templates
        self-documenting about what they're including.
        """
        return f"<{self.__class__.__name__}({self._ref.key()})>"
