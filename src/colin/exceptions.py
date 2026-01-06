"""Colin exceptions."""


class ColinError(Exception):
    """Base exception for Colin errors."""


class RefNotFoundError(ColinError):
    """Referenced document does not exist."""


class RefNotCompiledError(ColinError):
    """Referenced document has not been compiled yet.

    This error occurs when ref() is called for a project document that
    hasn't been compiled in this run and allow_stale=False (the default).
    """

    def __init__(self, target: str) -> None:
        """Initialize with the target that wasn't compiled.

        Args:
            target: The ref target that wasn't compiled.
        """
        self.target = target

        # Check if target appears to have an extension
        has_extension = "." in target.split("/")[-1]

        lines = [f"ref('{target}') failed - document not compiled."]
        if not has_extension:
            lines.append(f"Ensure '{target}' includes the file extension (e.g., '{target}.md').")
        lines.extend(
            [
                "Colin can only auto-detect dependencies for static ref targets.",
                f"For dynamic refs, add 'depends_on: [{target}]' to frontmatter,",
                f"or use ref('{target}', allow_stale=True) to accept stale/missing data.",
            ]
        )
        super().__init__("\n".join(lines))


class RefError(ColinError):
    """Error loading or replaying a Ref."""


class CyclicDependencyError(ColinError):
    """Dependency graph contains a cycle."""

    def __init__(self, cycle_path: list[str]) -> None:
        """Initialize with the cycle path.

        Args:
            cycle_path: List of URIs forming the cycle (last element connects back to first).
        """
        self.cycle_path = cycle_path
        path_str = " → ".join(cycle_path + [cycle_path[0]])  # Show A → B → C → A
        super().__init__(
            f"Cycle detected: {path_str}\nUse allow_stale=True on one ref to break the cycle."
        )


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


class UpstreamFailedError(ColinError):
    """Document skipped because an upstream dependency failed."""

    def __init__(self, failed_dependency: str) -> None:
        """Initialize with the failed dependency.

        Args:
            failed_dependency: URI of the dependency that failed.
        """
        self.failed_dependency = failed_dependency
        super().__init__(f"Skipped: upstream dependency '{failed_dependency}' failed")


class MultipleCompilationErrors(ColinError):
    """Multiple documents failed compilation."""

    def __init__(self, errors: dict[str, list[Exception]], skipped: set[str] | None = None) -> None:
        """Initialize with errors grouped by document.

        Args:
            errors: Dict mapping document URI to list of errors.
            skipped: Set of URIs that were skipped due to upstream failures.
        """
        self.errors = errors
        self.skipped = skipped or set()
        # Build summary message
        error_count = sum(len(errs) for errs in errors.values())
        doc_count = len(errors)
        super().__init__(f"Compilation failed: {error_count} error(s) in {doc_count} document(s)")


class ProjectNotInitializedError(ColinError):
    """Raised when a project needs initialization."""
