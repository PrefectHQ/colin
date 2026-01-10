"""Project provider - reads compiled artifacts from .colin/compiled/."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from pydantic import validate_call

from colin.compiler.cache import get_compile_context
from colin.models import DocumentMeta, FileOutputMeta, Manifest, Ref
from colin.providers.base import Provider
from colin.resources import Resource

if TYPE_CHECKING:
    from colin.compiler.sections import SectionsAccessor


class ProjectResource(Resource):
    """Resource returned by ProjectProvider.

    Path properties error on private (unpublished) files since they aren't in output/.
    """

    def __init__(
        self,
        content: str,
        ref: Ref,
        relative_path: str,
        output_path: Path,
        publish: bool = True,
        name: str | None = None,
        description: str | None = None,
        output_hash: str | None = None,
        output_format: str | None = None,
        sections: dict[str, str] | None = None,
    ) -> None:
        """Initialize a project resource.

        Args:
            content: Compiled output content.
            ref: The Ref for this resource.
            relative_path: Relative path within project (e.g., "greeting.md").
            output_path: Absolute path to output directory.
            publish: Whether this resource is published to output/.
            name: Resource name (defaults to filename).
            description: Resource description.
            output_hash: Hash of compiled output (used as version).
            output_format: Output format (json, yaml, markdown).
            sections: Named sections extracted from document.
        """
        super().__init__(content, ref)
        self._relative_path = Path(relative_path)
        self._output_path = output_path
        self._publish = publish
        self.name = name or self._relative_path.name
        self.description = description
        self._output_hash = output_hash
        self._output_format = output_format or "markdown"
        self._sections_data = sections or {}
        self._sections_cache: SectionsAccessor | None = None

    @property
    def path(self) -> Path:
        """Absolute path in output/. Errors on private (unpublished) files."""
        if not self._publish:
            raise ValueError(
                f"Cannot get path for private file '{self._relative_path}'. "
                "Private files are not published to output/. Use .content instead."
            )
        return self._output_path / self._relative_path

    @property
    def relative_path(self) -> Path:
        """Relative path within output/. Errors on private (unpublished) files."""
        if not self._publish:
            raise ValueError(
                f"Cannot get relative_path for private file '{self._relative_path}'. "
                "Private files are not published to output/. Use .content instead."
            )
        return self._relative_path

    @property
    def version(self) -> str:
        """Use output_hash from manifest if available, else content hash."""
        if self._output_hash is not None:
            return self._output_hash
        return super().version

    @property
    def sections(self) -> SectionsAccessor:
        """Access sections with format-aware parsing.

        Only available on ProjectResource since only compiled documents have sections.

        Returns:
            SectionsAccessor for dot/dict access to sections.
        """
        if self._sections_cache is None:
            from colin.compiler.sections import SectionsAccessor

            self._sections_cache = SectionsAccessor(self._sections_data, self._detect_format())
        return self._sections_cache

    def _detect_format(self) -> str:
        """Detect output format for format-aware section parsing.

        Returns:
            Output format (json, yaml, or markdown).
        """
        if self._output_format:
            return self._output_format

        # Infer from extension
        ext = self._relative_path.suffix.lower()
        if ext == ".json":
            return "json"
        elif ext in (".yaml", ".yml"):
            return "yaml"
        return "markdown"


class ProjectProvider(Provider):
    """Provider for reading compiled artifacts from .colin/compiled/.

    Uses manifest for version lookups and private detection.
    Path properties on resources resolve to output/.

    Template usage: ref("greeting.md") reads base_path/greeting.md
    """

    namespace: ClassVar[str] = "project"

    base_path: Path
    """Directory containing compiled artifacts (.colin/compiled/)."""

    output_path: Path | None = None
    """Output directory for path resolution (published outputs)."""

    manifest: Manifest | None = None
    """Manifest for version lookups and private detection."""

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

        # Security: ensure resolved path is within base_path (prevent path traversal)
        try:
            resolved.relative_to(self.base_path.resolve())
        except ValueError:
            raise FileNotFoundError(f"File not found: {path}") from None

        if not resolved.exists():
            raise FileNotFoundError(f"File not found: {path} (expected at {resolved})")

        content = resolved.read_text(encoding="utf-8")

        # Get metadata from manifest
        output_hash = self._get_output_hash(path)
        publish = self._should_publish(path)
        sections = self._get_sections(path)
        output_format = self._get_output_format(path)

        ref = Ref(
            provider=self.namespace,
            connection=self._connection,
            method="get",
            args={"path": path},
        )

        resource = ProjectResource(
            content=content,
            ref=ref,
            relative_path=path,
            output_path=self.output_path or self.base_path,
            publish=publish,
            name=path.split("/")[-1],
            output_hash=output_hash,
            output_format=output_format,
            sections=sections,
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

    def _get_file_output_meta(self, path: str) -> tuple[DocumentMeta | None, FileOutputMeta | None]:
        """Get document and file output metadata for a path.

        Returns:
            Tuple of (doc_meta, file_output_meta or None).
            file_output_meta is None if path is a main document output.
        """
        if self.manifest is None:
            return None, None
        doc_meta = self.manifest.get_document_by_output_path(path)
        if doc_meta is None:
            return None, None
        # Check if this is a file output (not the main document output)
        if path in doc_meta.file_outputs:
            return doc_meta, doc_meta.file_outputs[path]
        return doc_meta, None

    def _get_output_hash(self, path: str) -> str | None:
        """Get output_hash from manifest for a document by output_path."""
        doc_meta, file_meta = self._get_file_output_meta(path)
        if doc_meta is None:
            return None
        # Use file output hash if this is a file output
        if file_meta is not None:
            return file_meta.output_hash
        return doc_meta.output_hash

    def _should_publish(self, path: str) -> bool:
        """Check if a path should be published using manifest (authoritative source).

        The manifest is populated during compilation with the authoritative
        publish status. If the manifest or document is missing, assume published.
        """
        doc_meta, file_meta = self._get_file_output_meta(path)
        if doc_meta is None:
            return True
        # Use file output publish if this is a file output
        if file_meta is not None:
            # File outputs inherit from parent if publish is None
            if file_meta.publish is not None:
                return file_meta.publish
            return doc_meta.is_published
        return doc_meta.is_published

    def _get_sections(self, path: str) -> dict[str, str]:
        """Get sections from manifest for a document by output_path."""
        doc_meta, file_meta = self._get_file_output_meta(path)
        if doc_meta is None:
            return {}
        # Use file output sections if this is a file output
        if file_meta is not None:
            return file_meta.sections
        return doc_meta.sections

    def _get_output_format(self, path: str) -> str | None:
        """Get output format from manifest for a document by output_path."""
        doc_meta, file_meta = self._get_file_output_meta(path)
        if doc_meta is None:
            return None
        # Use file output format if this is a file output
        if file_meta is not None:
            return file_meta.format
        return None

    def get_functions(self) -> dict[str, Callable[..., Awaitable[object]]]:
        return {"get": self.get}
