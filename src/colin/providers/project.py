"""Project provider - FileProvider scoped to the project's target directory."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from colin.models import Address, Manifest
from colin.providers.file import FileProvider, FileResource


@dataclass
class ProjectResource(FileResource):
    """Domain object returned by ProjectProvider. Extends FileResource."""

    name: str = ""
    """Resource name (typically filename)."""

    description: str | None = None
    """Resource description."""

    def address(self) -> Address:
        return Address(
            provider="project",
            instance=self._instance,
            payload={"path": self.path},
        )


class ProjectProvider(FileProvider):
    """FileProvider scoped to the project's target directory.

    Reads compiled artifacts relative to base_path. Uses manifest
    for timestamps instead of file mtime.

    Template usage: ref("greeting.md") reads base_path/greeting.md
    """

    namespace: ClassVar[str] = "project"

    base_path: Path
    """Target directory containing compiled artifacts."""

    manifest: Manifest | None = None
    """Manifest for timestamp lookups."""

    async def load_uri(self, uri: str) -> ProjectResource:
        """Load compiled artifact by URI.

        Args:
            uri: Full URI (e.g., 'project://greeting.md').

        Returns:
            ProjectResource with content and metadata.
        """
        path = uri.split("://", 1)[1] if "://" in uri else uri
        return await self._fetch(path)

    async def load_address(self, payload: dict[str, Any]) -> ProjectResource:
        """Load compiled artifact from address payload.

        Args:
            payload: Dict with 'path' key (relative to base_path).

        Returns:
            ProjectResource with content and metadata.
        """
        path = payload["path"]
        return await self._fetch(path)

    async def _fetch(self, path: str) -> ProjectResource:
        """Fetch project resource by relative path."""
        resolved = (self.base_path / path).resolve()

        if not resolved.exists():
            raise FileNotFoundError(f"File not found: {path} (expected at {resolved})")

        content = resolved.read_text(encoding="utf-8")
        updated = self._get_compiled_at(path)

        return ProjectResource(
            path=path,
            _content=content,
            name=path.split("/")[-1],
            _last_updated=updated,
            _instance=self._instance,
        )

    async def get_last_updated(self, payload: dict[str, Any]) -> datetime | None:
        """Get compiled_at from manifest for a document.

        Args:
            payload: Dict with 'path' key.

        Returns:
            Document's compiled_at time, or None if not in manifest.
        """
        path = payload["path"]
        return self._get_compiled_at(path)

    def _get_compiled_at(self, path: str) -> datetime | None:
        """Get compiled_at time from manifest."""
        if self.manifest is None:
            return None
        uri = f"project://{path}"
        doc_meta = self.manifest.get_document(uri)
        if doc_meta is None:
            return None
        return doc_meta.compiled_at
