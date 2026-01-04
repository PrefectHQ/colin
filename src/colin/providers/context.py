"""Context for provider functions."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from colin.compiler.state import OperationState
from colin.models import Manifest

if TYPE_CHECKING:
    from colin.resources import Resource


@dataclass
class ProviderContext:
    """Context passed to provider functions."""

    manifest: Manifest
    document_uri: str
    doc_state: OperationState | None
    ref: Callable[["str | Resource"], Awaitable["Resource"]]
    track_ref: Callable[[str], None]
