"""Base output target."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

logger = logging.getLogger(__name__)


class Target(ABC):
    """Base class for output targets.

    Output targets control:
    1. Where files are written (resolve_path)
    2. Where manifests are placed (get_manifest_locations)

    Manifest location = ownership scope. A manifest at `output/stripe/.colin-manifest.json`
    claims ownership of `output/stripe/` for cleaning purposes.

    Targets are instantiated from TOML config:
        [project.output]
        target = "local"  # maps to LocalTarget
        path = "output/"  # passed as kwarg
    """

    #: Target name used in config (e.g., "local", "skill", "claude-skill")
    name: ClassVar[str]

    @abstractmethod
    def resolve_path(self, project_root: Path) -> Path:
        """Resolve the output directory path.

        Args:
            project_root: Project root directory.

        Returns:
            Absolute path to the output directory.
        """
        ...

    def get_manifest_locations(self, file_paths: list[str]) -> list[str]:
        """Determine where manifests should be written.

        Each returned path (relative to output dir) gets a `.colin-manifest.json`
        that claims ownership of that directory. This enables safe cleaning of
        stale files without affecting user-created files.

        The default implementation returns `[""]` (root), meaning one manifest
        at the output root that owns the entire directory.

        Override this for targets that write to subdirectories (like skills
        which writes to `output/<server-name>/`).

        Args:
            file_paths: List of file paths (relative to output dir) being written.

        Returns:
            List of directory paths (relative to output dir) where manifests
            should be written. Empty string means output root.
        """
        return [""]  # Default: root owns everything
