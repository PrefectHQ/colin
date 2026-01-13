"""Local filesystem output target."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from colin.output.base import Target


class LocalTarget(Target):
    """Local filesystem output target.

    Writes to a specified path within or relative to the project directory.
    Uses a single manifest at root that owns the entire directory.

    Config:
        [project.output]
        target = "local"
        path = "output/"
    """

    name: ClassVar[str] = "local"

    def __init__(self, path: str) -> None:
        """Initialize local target.

        Args:
            path: Output path (relative to project root or absolute).
        """
        self._path = Path(path)

    def resolve_path(self, project_root: Path) -> Path:
        """Resolve output path relative to project root."""
        if self._path.is_absolute():
            return self._path.resolve()
        return (project_root / self._path).resolve()
