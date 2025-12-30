"""YAML renderer."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

from colin.renders.base import Renderer

if TYPE_CHECKING:
    from colin.models import CompiledDocument


class YAMLRenderer(Renderer):
    """Renderer for YAML output.

    Validates that content is valid YAML.
    """

    name: str = "yaml"
    extension: str = ".yaml"

    def validate(self, document: CompiledDocument) -> None:
        """Validate that document output is valid YAML.

        Args:
            document: The compiled document.

        Raises:
            yaml.YAMLError: If content is not valid YAML.
        """
        yaml.safe_load(document.output)
