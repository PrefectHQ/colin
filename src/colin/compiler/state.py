"""Compilation state tree for progress tracking.

Provides a tree structure where the compiler updates state and the CLI
reads/renders it. No event matching needed - state is always consistent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import Self


class Status(Enum):
    """Operation status."""

    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"  # Upstream dependency failed


@dataclass
class OperationState:
    """A node in the state tree.

    Represents a document or operation (LLM call, extract, ref, etc.).
    Use as a context manager to auto-handle start/done/fail transitions.

    Example:
        with doc_state.child("llm:auto:abc", detail="gpt-4"):
            result = await call_llm(...)
    """

    name: str
    status: Status = Status.PENDING
    detail: str | None = None
    cached: bool = False
    error: str | None = None
    parent: OperationState | None = None
    children: list[OperationState] = field(default_factory=list)

    def __enter__(self) -> Self:
        """Start the operation."""
        self.status = Status.PROCESSING
        return self

    def __exit__(
        self, exc_type: type | None, exc_val: BaseException | None, exc_tb: object
    ) -> bool:
        """Complete the operation (done on success, failed on exception)."""
        if exc_type is None:
            self.status = Status.DONE
        else:
            self.status = Status.FAILED
            self.error = str(exc_val) if exc_val else None
        return False  # Don't suppress exceptions

    def child(self, name: str, detail: str | None = None) -> OperationState:
        """Create and attach a child operation.

        Args:
            name: Operation name (e.g., "llm:auto:abc123", "ref:greeting", "mcp:server")
            detail: Optional detail (e.g., model name, URI)

        Returns:
            The new child state.
        """
        child_state = OperationState(name=name, detail=detail, parent=self)
        self.children.append(child_state)
        return child_state

    def mark_cached(self) -> None:
        """Mark this operation as served from cache (skips context manager)."""
        self.cached = True
        self.status = Status.DONE

    def mark_skipped(self, reason: str | None = None) -> None:
        """Mark this operation as skipped due to upstream failure."""
        self.status = Status.SKIPPED
        self.error = reason


@dataclass
class CompilationState:
    """Root state for a compilation run.

    Holds all document states. The engine populates this during discovery,
    and updates status as compilation proceeds.
    """

    documents: dict[str, OperationState] = field(default_factory=dict)

    def add_document(self, uri: str) -> OperationState:
        """Add a document to track.

        Args:
            uri: Document URI.

        Returns:
            The new document state.
        """
        state = OperationState(name=uri)
        self.documents[uri] = state
        return state

    def get_document(self, uri: str) -> OperationState | None:
        """Get state for a document.

        Args:
            uri: Document URI.

        Returns:
            The document state, or None if not found.
        """
        return self.documents.get(uri)
