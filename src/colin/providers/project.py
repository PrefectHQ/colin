"""Project provider for project:// URIs."""

from colin.providers.base import Provider


class ProjectProvider(Provider):
    """Provider for project:// URIs. Reads from compiled artifacts.

    Wraps another provider to provide the project:// scheme for template refs.
    The ref() function handles creating RefResult and tracking dependencies.

    By convention, instantiated with Storage (for artifact reads), but typed
    to accept any Provider since it only needs read capability.
    """

    scheme: str = "project"

    def __init__(self, provider: Provider) -> None:
        """Initialize project provider.

        Args:
            provider: Underlying provider for reads (typically artifact storage).
        """
        self._provider = provider

    async def read(self, path: str) -> str:
        """Read compiled artifact by path.

        Args:
            path: Relative path (e.g., 'greeting.md').

        Returns:
            Raw content.
        """
        return await self._provider.read(path)
