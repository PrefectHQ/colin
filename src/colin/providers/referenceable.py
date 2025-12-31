"""Referenceable protocol for objects that can be passed to ref()."""

from datetime import datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from colin.models import RefResult


@runtime_checkable
class Referenceable(Protocol):
    """Protocol for objects that can be converted to RefResult via ref().

    Objects implementing this protocol can be passed to ref() to create
    tracked dependencies. The ref() function will call to_ref_result()
    to convert the domain object into a RefResult.

    Example:
        {{ ref(mcp.greeter.resource('colin://hello')) }}
    """

    @property
    def uri(self) -> str:
        """URI that uniquely identifies this resource."""
        ...

    @property
    def last_updated(self) -> datetime:
        """When this resource was last modified.

        Used for staleness detection. If unknown, return current time
        (which will treat the resource as potentially changed).
        """
        ...

    def to_ref_result(self) -> "RefResult":
        """Convert to RefResult for dependency tracking."""
        ...
