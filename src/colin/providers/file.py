"""File provider for reading files from the filesystem."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar

from pydantic import validate_call

from colin.compiler.cache import get_compile_context
from colin.models import Ref
from colin.providers.base import Provider
from colin.resources import Resource


class FileResource(Resource):
    """Resource returned by FileProvider."""

    def __init__(
        self,
        content: str,
        ref: Ref,
        path: str,
        mtime: datetime | None = None,
    ) -> None:
        """Initialize a file resource.

        Args:
            content: File content.
            ref: The Ref for this resource.
            path: Absolute path to the file.
            mtime: File modification time (used as version).
        """
        super().__init__(content, ref)
        self.path = path
        self._mtime = mtime

    @property
    def version(self) -> str:
        """Use mtime as version if available, else content hash."""
        if self._mtime is not None:
            return self._mtime.isoformat()
        return super().version


class FileProvider(Provider):
    """Provider for reading files from the filesystem.

    Template usage: {{ file.get("/path/to/file.txt") }}
    """

    namespace: ClassVar[str] = "file"

    _connection: str = ""

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        yield

    @validate_call
    async def get(self, path: str, watch: bool = True) -> FileResource:
        """Read a file from the filesystem.

        Template usage: {{ file.get("/path/to/file.txt") }}

        Args:
            path: Absolute or ~ path to the file.
            watch: Whether to track this ref for staleness (default True).

        Returns:
            FileResource with content and metadata.
        """
        expanded = os.path.expanduser(path)
        resolved = Path(expanded).resolve()

        if not resolved.exists():
            raise FileNotFoundError(f"File not found: {path}")

        content = resolved.read_text(encoding="utf-8")
        mtime = resolved.stat().st_mtime
        last_updated = datetime.fromtimestamp(mtime, tz=timezone.utc)

        ref = Ref(
            provider=self.namespace,
            connection=self._connection,
            method="get",
            args={"path": path},
        )

        resource = FileResource(
            content=content,
            ref=ref,
            path=str(resolved),
            mtime=last_updated,
        )

        if watch:
            ctx = get_compile_context()
            if ctx:
                ctx.track(ref, resource.version)

        return resource

    async def get_ref_version(self, ref: Ref) -> str:
        """Get file version using mtime (no content fetch).

        Args:
            ref: The Ref to check.

        Returns:
            File mtime as ISO string.
        """
        path = ref.args["path"]
        expanded = os.path.expanduser(path)
        resolved = Path(expanded).resolve()

        if not resolved.exists():
            raise FileNotFoundError(f"File not found: {path}")

        mtime = resolved.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()

    def get_functions(self) -> dict[str, Callable[..., Awaitable[object]]]:
        return {"get": self.get}
