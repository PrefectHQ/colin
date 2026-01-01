"""Addressable base class for objects that can be passed to ref()."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from colin.models import Address


class Addressable(ABC):
    """Base class for objects returned by ref() and provider functions.

    Domain objects (MCPResource, HTTPResource, S3Resource, etc.) inherit
    from this class. ref() returns these objects directly.

    Subclasses must:
    - Provide `content` property returning the resource content
    - Provide `last_updated` property returning modification time
    - Implement `address()` returning structured Address for re-fetching

    The shared `__str__()` implementation returns content, so resources
    can be used directly in templates: {{ ref("s3://bucket/file.csv") }}

    Example:
        @dataclass
        class S3Resource(Addressable):
            _content: str
            _last_modified: datetime
            bucket: str
            key: str

            @property
            def content(self) -> str:
                return self._content

            @property
            def last_updated(self) -> datetime:
                return self._last_modified

            def address(self) -> Address:
                return Address(
                    provider="s3",
                    instance="",
                    payload={"bucket": self.bucket, "key": self.key},
                )
    """

    @property
    @abstractmethod
    def content(self) -> str:
        """The content of this resource."""
        ...

    @property
    @abstractmethod
    def last_updated(self) -> datetime:
        """When this resource was last modified."""
        ...

    @abstractmethod
    def address(self) -> "Address":
        """Return structured address for re-fetching this resource.

        The address contains provider, instance, and a payload dict
        with provider-specific data needed to re-fetch this resource.
        """
        ...

    def __str__(self) -> str:
        """Return content for template use."""
        return self.content
