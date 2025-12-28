"""Colin exceptions."""


class ColinError(Exception):
    """Base exception for Colin errors."""


class RefNotFoundError(ColinError):
    """Referenced document does not exist."""


class CyclicDependencyError(ColinError):
    """Dependency graph contains a cycle."""


class TemplateSyntaxError(ColinError):
    """Jinja template has syntax errors."""


class FrontmatterError(ColinError):
    """Invalid frontmatter in .colin file."""


class CompilationError(ColinError):
    """Error during document compilation."""

    def __init__(self, message: str, document_uri: str | None = None) -> None:
        """Initialize with optional document context.

        Args:
            message: Error message.
            document_uri: URI of document that failed compilation.
        """
        self.document_uri = document_uri
        super().__init__(message)


class MultipleCompilationErrors(ColinError):
    """Multiple documents failed compilation."""

    def __init__(self, errors: dict[str, list[Exception]]) -> None:
        """Initialize with errors grouped by document.

        Args:
            errors: Dict mapping document URI to list of errors.
        """
        self.errors = errors
        # Build summary message
        error_count = sum(len(errs) for errs in errors.values())
        doc_count = len(errors)
        super().__init__(f"Compilation failed: {error_count} error(s) in {doc_count} document(s)")


class ProjectNotInitializedError(ColinError):
    """Raised when a project needs initialization."""
