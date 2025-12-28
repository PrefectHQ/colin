"""Manifest API functions."""

from __future__ import annotations

import json
from pathlib import Path

from colin.models import Manifest


def load_manifest(path: Path) -> Manifest:
    """Load manifest from JSON file.

    Args:
        path: Path to manifest.json file.

    Returns:
        Manifest object (empty if file doesn't exist).
    """
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return Manifest.model_validate(data)
    return Manifest()


def save_manifest(manifest: Manifest, path: Path) -> None:
    """Save manifest to JSON file.

    Args:
        manifest: Manifest to save.
        path: Path to save manifest.json.
    """
    data = manifest.model_dump(mode="json")
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
