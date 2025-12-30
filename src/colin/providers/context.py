"""Context for provider functions."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from colin.compiler.state import OperationState
from colin.models import Manifest, RefResult

if TYPE_CHECKING:
    from colin.providers.referenceable import Referenceable


@dataclass
class ProviderContext:
    """Context passed to provider functions."""

    manifest: Manifest
    document_uri: str
    doc_state: OperationState | None
    ref: Callable[["str | Referenceable"], Awaitable[RefResult]]
    track_ref: Callable[[str], None]
    extract: Callable[[str, str, str | None, str | None], Awaitable[str]]
