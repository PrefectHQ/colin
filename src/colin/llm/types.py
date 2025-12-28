"""LLM response types for Colin."""

from pydantic import BaseModel


class UseExisting(BaseModel):
    """Signal to use existing/cached content instead of generating new.

    LLMs can return this type instead of text to indicate the previous
    output is still valid, saving tokens when maintaining stability.
    """

    pass


# Union type for agent output - either new text or signal to use existing
LLMOutput = str | UseExisting
