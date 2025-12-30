"""JSON renderer."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from colin.renders.base import Renderer

if TYPE_CHECKING:
    from colin.models import CompiledDocument


class JSONRenderer(Renderer):
    """Renderer for JSON output.

    Validates that content is valid JSON.
    """

    name: str = "json"
    extension: str = ".json"

    def validate(self, document: CompiledDocument) -> None:
        """Validate that document output is valid JSON.

        Args:
            document: The compiled document.

        Raises:
            json.JSONDecodeError: If content is not valid JSON.
        """
        json.loads(document.output)
