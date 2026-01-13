"""Skill output targets."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar, Literal

from colin.output.base import Target

logger = logging.getLogger(__name__)


class SkillTarget(Target):
    """Generic skill output target.

    Writes skills to a specified path. Uses per-subdirectory manifests
    so each skill (server) gets its own manifest for granular cleaning.

    Config:
        [project.output]
        target = "skill"
        path = "output/skills/"
    """

    name: ClassVar[str] = "skill"

    def __init__(self, path: str) -> None:
        """Initialize skill target.

        Args:
            path: Output path (required).
        """
        self._path = Path(path)

    def resolve_path(self, project_root: Path) -> Path:
        """Resolve output path relative to project root."""
        if self._path.is_absolute():
            return self._path.resolve()
        return (project_root / self._path).resolve()

    def get_manifest_locations(self, file_paths: list[str]) -> list[str]:
        """Return one manifest per first-level subdirectory.

        For files like:
          - stripe/SKILL.md
          - stripe/greet.md
          - github/SKILL.md

        Returns: ["github", "stripe"]

        If all files are at root level, returns [""] (root manifest).
        """
        roots: set[str] = set()
        for path in file_paths:
            parts = Path(path).parts
            if len(parts) > 1:
                # File is in a subdirectory - add the first-level dir
                roots.add(parts[0])

        # If we have subdirectories, return them sorted
        if roots:
            return sorted(roots)

        # No subdirectories - all files at root
        return [""]


class ClaudeSkillTarget(SkillTarget):
    """Claude Code skill output target.

    Writes skills to Claude's skill directory. Supports user-scoped
    (~/.claude/skills/) or project-scoped (.claude/skills/) output.

    Config:
        [project.output]
        target = "claude-skill"
        scope = "user"  # or "project"
        # path is optional - overrides default location
    """

    name: ClassVar[str] = "claude-skill"

    def __init__(
        self,
        scope: Literal["user", "project"] = "user",
        path: str | None = None,
    ) -> None:
        """Initialize Claude skill target.

        Args:
            scope: "user" for ~/.claude/skills/, "project" for .claude/skills/
            path: Optional path override. If provided, logs info about custom path.
        """
        self._scope = scope
        self._custom_path = Path(path) if path else None

        if self._custom_path:
            logger.info(
                f"Claude skill target using custom path: {self._custom_path} "
                f"(default for scope='{scope}' would be {self._get_default_path()})"
            )

    def _get_default_path(self) -> str:
        """Get default path description for the current scope."""
        if self._scope == "user":
            return "~/.claude/skills/"
        return ".claude/skills/"

    def resolve_path(self, project_root: Path) -> Path:
        """Resolve output path based on scope or custom path."""
        if self._custom_path:
            if self._custom_path.is_absolute():
                return self._custom_path.resolve()
            return (project_root / self._custom_path).resolve()

        if self._scope == "user":
            return (Path.home() / ".claude" / "skills").resolve()

        # Project scope - look for .claude folder
        # Start from project root and walk up to find .claude
        current = project_root.resolve()
        while current != current.parent:
            claude_dir = current / ".claude"
            if claude_dir.is_dir():
                return (claude_dir / "skills").resolve()
            current = current.parent

        # No .claude found - create in project root
        logger.info(
            f"No .claude directory found above {project_root}, "
            "creating .claude/skills/ in project root"
        )
        return (project_root / ".claude" / "skills").resolve()
