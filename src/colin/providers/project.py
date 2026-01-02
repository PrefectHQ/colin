"""Project provider - reads compiled artifacts from the project's target directory."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import ClassVar

from pydantic import validate_call

from colin.models import Manifest, Ref
from colin.providers.base import Provider
from colin.providers.cache import get_compile_context
from colin.providers.resource import Resource


class ProjectResource(Resource):
    """Resource returned by ProjectProvider."""

    def __init__(
        self,
        content: str,
        ref: Ref,
        path: str,
        name: str | None = None,
        description: str | None = None,
        output_hash: str | None = None,
    ) -> None:
        """Initialize a project resource.

        Args:
            content: Compiled output content.
            ref: The Ref for this resource.
            path: Relative path within project (e.g., "greeting.md").
            name: Resource name (defaults to filename).
            description: Resource description.
            output_hash: Hash of compiled output (used as version).
        """
        super().__init__(content, ref)
        self.path = path
        self.name = name or path.split("/")[-1]
        self.description = description
        self._output_hash = output_hash

    @property
    def version(self) -> str:
        """Use output_hash from manifest if available, else content hash."""
        if self._output_hash is not None:
            return self._output_hash
        return super().version


class ProjectProvider(Provider):
    """Provider for reading compiled artifacts from the project's target directory.

    Uses manifest for version lookups (output_hash) instead of file mtime.

    Template usage: ref("greeting.md") reads base_path/greeting.md
    """

    namespace: ClassVar[str] = "project"

    base_path: Path
    """Target directory containing compiled artifacts."""

    manifest: Manifest | None = None
    """Manifest for version lookups."""

    _connection: str = ""

    @validate_call
    async def get(self, path: str, watch: bool = True) -> ProjectResource:
        """Read a compiled artifact by relative path.

        Args:
            path: Relative path within the project (e.g., "greeting.md").
            watch: Whether to track this ref for staleness (default True).

        Returns:
            ProjectResource with content and metadata.
        """
        resolved = (self.base_path / path).resolve()

        if not resolved.exists():
            raise FileNotFoundError(f"File not found: {path} (expected at {resolved})")

        content = resolved.read_text(encoding="utf-8")

        # Get output_hash from manifest for version
        output_hash = self._get_output_hash(path)

        ref = Ref(
            provider=self.namespace,
            connection=self._connection,
            method="get",
            args={"path": path},
        )

        resource = ProjectResource(
            content=content,
            ref=ref,
            path=path,
            name=path.split("/")[-1],
            output_hash=output_hash,
        )

        if watch:
            ctx = get_compile_context()
            if ctx:
                ctx.track(ref, resource.version)

        return resource

    async def load_uri(self, uri: str) -> ProjectResource:
        """Load compiled artifact by URI.

        Args:
            uri: Full URI (e.g., 'project://greeting.md').

        Returns:
            ProjectResource with content and metadata.
        """
        path = uri.split("://", 1)[1] if "://" in uri else uri
        return await self.get(path, watch=False)

    async def get_ref_version(self, ref: Ref) -> str:
        """Get version from manifest (no file read).

        Args:
            ref: The Ref to check.

        Returns:
            Output hash from manifest, or content hash if not in manifest.
        """
        path = ref.args["path"]
        output_hash = self._get_output_hash(path)

        if output_hash is not None:
            return output_hash

        # Fall back to reading file and computing hash
        resource = await self._load_ref(ref)
        return resource.version

    def _get_output_hash(self, path: str) -> str | None:
        """Get output_hash from manifest for a document."""
        if self.manifest is None:
            return None
        uri = f"project://{path}"
        doc_meta = self.manifest.get_document(uri)
        if doc_meta is None:
            return None
        return doc_meta.output_hash

    def get_functions(self) -> dict[str, Callable[..., Awaitable[object]]]:
        return {"get": self.get}
