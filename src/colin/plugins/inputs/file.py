"""File input plugin for local model files."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import frontmatter

from colin.models import ColinConfig, Frontmatter, RefResult

if TYPE_CHECKING:
    pass


class FileInputPlugin:
    """Input plugin for local model files.

    This is the default input plugin that reads models from the local filesystem.
    Models are markdown files with optional YAML frontmatter.
    """

    scheme: str = "project"

    def __init__(self, model_dirs: list[Path], target_dir: Path) -> None:
        """Initialize the file input plugin.

        Args:
            model_dirs: Directories containing model files.
            target_dir: Directory where compiled outputs are written.
        """
        self.model_dirs = model_dirs
        self.target_dir = target_dir

    def normalize_uri(self, uri: str) -> str:
        """Normalize a URI to project:// format.

        Converts shorthand refs like 'data' to 'project://data.md'.

        Args:
            uri: URI in any format (shorthand or full).

        Returns:
            Normalized project:// URI.
        """
        # Already normalized
        if uri.startswith("project://"):
            return uri

        # Has a different scheme - leave as-is
        if "://" in uri:
            return uri

        # Schemaless shorthand - normalize to project://
        # Add .md extension if missing
        if not uri.endswith(".md"):
            uri = f"{uri}.md"
        return f"project://{uri}"

    def _extract_path_from_uri(self, uri: str) -> str:
        """Extract the path portion from a project:// URI.

        Args:
            uri: A project:// URI (e.g., project://data.md).

        Returns:
            The path without scheme (e.g., data.md).
        """
        if uri.startswith("project://"):
            return uri[len("project://") :]
        return uri

    def uri_to_model_path(self, uri: str) -> Path | None:
        """Convert a URI to a model file path.

        Args:
            uri: Model URI (e.g., 'project://data.md' or shorthand 'data').

        Returns:
            Path to the model file, or None if not found.
        """
        # Normalize and extract path
        normalized = self.normalize_uri(uri)
        path_part = self._extract_path_from_uri(normalized)

        for model_dir in self.model_dirs:
            candidate = model_dir / path_part
            if candidate.exists():
                return candidate
        return None

    def uri_to_target_path(self, uri: str) -> Path:
        """Convert a URI to a target file path.

        Args:
            uri: Model URI (e.g., 'project://data.md').

        Returns:
            Path to the compiled output file.
        """
        path_part = self._extract_path_from_uri(uri)
        return self.target_dir / path_part

    async def fetch(self, uri: str) -> RefResult:
        """Fetch content and metadata for a URI.

        Args:
            uri: The URI to fetch.

        Returns:
            RefResult with content and metadata.

        Raises:
            FileNotFoundError: If the compiled output doesn't exist.
        """
        target_path = self.uri_to_target_path(uri)
        model_path = self.uri_to_model_path(uri)

        if not target_path.exists():
            raise FileNotFoundError(f"Compiled output not found: {target_path}")

        content = target_path.read_text(encoding="utf-8")

        # Get template source if available
        template = ""
        if model_path and model_path.exists():
            template = model_path.read_text(encoding="utf-8")

        # Extract name and description from model frontmatter
        path_part = self._extract_path_from_uri(uri)
        name: str = Path(path_part).stem  # Get filename without extension
        description: str | None = None
        if model_path and model_path.exists():
            post = frontmatter.loads(template)
            metadata: dict[str, object] = {k: v for k, v in post.metadata.items() if k != "colin"}
            name_value = metadata.get("name")
            if isinstance(name_value, str):
                name = name_value
            desc_value = metadata.get("description")
            if isinstance(desc_value, str):
                description = desc_value

        # Get modification time as updated timestamp
        stat = target_path.stat()
        updated = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

        return RefResult(
            name=name,
            description=description,
            content=content,
            template=template,
            updated=updated,
            uri=uri,
        )

    async def hash(self, uri: str) -> str:
        """Get content hash for change detection.

        Args:
            uri: The URI to hash.

        Returns:
            A hash string representing the model content.

        Raises:
            FileNotFoundError: If the model file doesn't exist.
        """
        model_path = self.uri_to_model_path(uri)
        if model_path is None or not model_path.exists():
            raise FileNotFoundError(f"Model file not found for: {uri}")

        content = model_path.read_text(encoding="utf-8")
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def discover_documents(self) -> list[tuple[str, Path]]:
        """Find all .md files in model directories.

        Excludes:
        - Files under the target directory
        - Files under directories containing colin.toml (nested projects)

        Returns:
            List of (uri, path) tuples for all discovered documents.
        """
        documents: list[tuple[str, Path]] = []
        target_resolved = self.target_dir.resolve()

        for model_dir in self.model_dirs:
            if not model_dir.exists():
                continue

            for path in model_dir.rglob("*.md"):
                # Skip files in target directory
                try:
                    path.resolve().relative_to(target_resolved)
                    continue  # Path is under target dir, skip it
                except ValueError:
                    pass  # Path is not under target dir, continue

                # Skip files in nested projects (directories with colin.toml)
                if self._is_in_nested_project(path, model_dir):
                    continue

                uri = self._path_to_uri(path, model_dir)
                documents.append((uri, path))

        return sorted(documents, key=lambda x: x[0])

    def _is_in_nested_project(self, path: Path, model_dir: Path) -> bool:
        """Check if path is inside a nested Colin project.

        Args:
            path: Path to check.
            model_dir: Root model directory.

        Returns:
            True if path is in a nested project (has colin.toml between it and model_dir).
        """
        current = path.parent
        model_resolved = model_dir.resolve()

        while current.resolve() != model_resolved:
            if (current / "colin.toml").exists():
                return True
            if current.parent == current:
                break
            current = current.parent

        return False

    def _path_to_uri(self, path: Path, model_dir: Path) -> str:
        """Convert a file path to a project:// URI.

        Args:
            path: Path to the model file.
            model_dir: Base model directory.

        Returns:
            URI string in project:// format (e.g., project://data.md).
        """
        relative = path.relative_to(model_dir)
        return f"project://{relative}"

    def parse_frontmatter(self, path: Path) -> tuple[Frontmatter, str]:
        """Parse frontmatter from a model file.

        Args:
            path: Path to the model file.

        Returns:
            Tuple of (Frontmatter, template_content).
        """
        content = path.read_text(encoding="utf-8")
        post = frontmatter.loads(content)

        # Extract colin config
        raw_colin = post.metadata.pop("colin", {})
        colin_data = cast(dict[str, Any], raw_colin) if isinstance(raw_colin, dict) else {}
        colin_config = ColinConfig.model_validate(colin_data)

        # Rest is document metadata
        metadata = cast(dict[str, Any], post.metadata)
        fm = Frontmatter(colin=colin_config, metadata=metadata)

        return fm, post.content
