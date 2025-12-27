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
