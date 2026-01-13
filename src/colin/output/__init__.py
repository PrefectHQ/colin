"""Output targets for Colin."""

from colin.output.base import Target
from colin.output.local import LocalTarget
from colin.output.skills import ClaudeSkillTarget, SkillTarget

__all__ = [
    "ClaudeSkillTarget",
    "LocalTarget",
    "SkillTarget",
    "Target",
]

# Registry mapping target names to classes
TARGET_REGISTRY: dict[str, type[Target]] = {
    "local": LocalTarget,
    "skill": SkillTarget,
    "claude-skill": ClaudeSkillTarget,
}


def get_target(name: str) -> type[Target]:
    """Get target class by name.

    Args:
        name: Target name from config.

    Returns:
        Target class.

    Raises:
        ValueError: If target name is unknown.
    """
    if name not in TARGET_REGISTRY:
        valid = ", ".join(sorted(TARGET_REGISTRY.keys()))
        raise ValueError(f"Unknown output target '{name}'. Valid targets: {valid}")
    return TARGET_REGISTRY[name]
