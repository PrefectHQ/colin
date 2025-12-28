"""Prompt template rendering for LLM calls."""

from jinja2 import Environment, PackageLoader

# Separate Jinja env for prompt templates - isolated from main compiler.
# Uses PackageLoader to load templates from the package resources.
_prompt_env = Environment(
    loader=PackageLoader("colin.llm", "prompts"),
    autoescape=False,
)


def render_extract_prompt(
    content: str,
    prompt: str,
    previous_output: str | None = None,
) -> str:
    """Render the extraction prompt template.

    Args:
        content: The content to extract from.
        prompt: What to extract.
        previous_output: Previous extraction output for stability.

    Returns:
        Rendered prompt string.
    """
    template = _prompt_env.get_template("extract.md")
    return template.render(
        content=content,
        prompt=prompt,
        previous_output=previous_output,
    )


def render_complete_prompt(
    body: str,
    previous_output: str | None = None,
) -> str:
    """Render the completion prompt template.

    Args:
        body: The prompt body (from {% llm %} block).
        previous_output: Previous output for stability.

    Returns:
        Rendered prompt string.
    """
    template = _prompt_env.get_template("complete.md")
    return template.render(
        body=body,
        previous_output=previous_output,
    )
