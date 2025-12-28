"""Compilation state tree for progress tracking.

Provides a tree structure where the compiler updates state and the CLI
reads/renders it. No event matching needed - state is always consistent.
"""

from dataclasses import dataclass, field
from enum import Enum


class Status(Enum):
    """Operation status."""

    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    CACHED = "cached"
    REF = "ref"


@dataclass
class OperationState:
    """A node in the state tree.

    Represents a document or operation (LLM call, extract, ref, etc.).
    Children are attached via the child() method which does mutual attachment.
    """

    name: str
    status: Status = Status.PENDING
    detail: str | None = None
    parent: "OperationState | None" = None
    children: list["OperationState"] = field(default_factory=list)

    def child(self, name: str, detail: str | None = None) -> "OperationState":
        """Create and attach a child operation.

        Mutual attachment: child.parent = self AND self.children.append(child)
        This allows traversal in both directions.

        Args:
            name: Operation name (e.g., "llm:auto:abc123", "extract", "ref:greeting")
            detail: Optional detail (e.g., model name)

        Returns:
            The new child state.
        """
        child_state = OperationState(name=name, detail=detail, parent=self)
        self.children.append(child_state)
        return child_state

    def start(self) -> None:
        """Mark this operation as processing."""
        self.status = Status.PROCESSING

    def done(self) -> None:
        """Mark this operation as done."""
        self.status = Status.DONE

    def fail(self, error: str | None = None) -> None:
        """Mark this operation as failed.

        Args:
            error: Optional error message to store in detail.
        """
        self.status = Status.FAILED
        if error:
            self.detail = error

    def cached(self) -> None:
        """Mark this operation as served from cache."""
        self.status = Status.CACHED

    def ref(self) -> None:
        """Mark this operation as a ref resolution."""
        self.status = Status.REF


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
