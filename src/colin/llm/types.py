"""LLM response types for Colin."""

from typing import Literal

from pydantic import BaseModel


class UseExisting(BaseModel):
    """Signal to use existing/cached content instead of generating new.

    LLMs can return this type instead of text to indicate the previous
    output is still valid, saving tokens when maintaining stability.
    """

    pass


# Union type for agent output - either new text or signal to use existing
LLMOutput = str | UseExisting


def create_classification_model(labels: list[str | bool], multi: bool = False) -> type[BaseModel]:
    """Create a Pydantic model for classification output validation.

    Uses Literal types for single-label classification, which provides
    better type safety and validation than dynamically created enums.

    Args:
        labels: List of valid label values (strings or booleans).
        multi: Whether to allow multiple labels.

    Returns:
        Pydantic model class for classification output.
    """
    # Create Literal type from labels tuple
    labels_tuple = tuple(labels)
    LabelLiteral = Literal[labels_tuple]  # type: ignore[valid-type]

    if multi:

        class ClassificationOutput(BaseModel):
            """Multi-label classification output."""

            labels: list[LabelLiteral]

        return ClassificationOutput
    else:

        class ClassificationOutput(BaseModel):
            """Single-label classification output."""

            label: LabelLiteral

        return ClassificationOutput
