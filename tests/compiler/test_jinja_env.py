"""Tests for Jinja environment bindings."""

from pathlib import Path

from colin.compiler.context import CompileContext
from colin.compiler.jinja_env import bind_context_to_environment, create_jinja_environment
from colin.models import Manifest
from colin.providers.http import HTTPProvider
from colin.providers.llm import LLMProvider
from colin.providers.manager import ProviderManager
from colin.providers.project import ProjectProvider


def test_bind_context_sets_colin_namespace(tmp_path: Path) -> None:
    """colin namespace exposes providers."""
    project_provider = ProjectProvider(base_path=tmp_path)
    context = CompileContext(
        manifest=Manifest(),
        document_uri="project://test.md",
        project_provider=project_provider,
    )

    provider_manager = ProviderManager()
    provider_manager.register(HTTPProvider())
    provider_manager.register(LLMProvider())

    env = create_jinja_environment()

    bind_context_to_environment(env, context, provider_manager)

    # colin namespace contains providers
    colin = env.globals["colin"]
    assert hasattr(colin, "llm")
    assert hasattr(colin, "http")
    # Root-level shortcuts are removed (no mcp, llm, http at root)
    assert "llm" not in env.globals
    assert "http" not in env.globals
    assert "mcp" not in env.globals
    # llm_extract and llm_classify are filters
    assert "llm_extract" in env.filters
    assert "llm_classify" in env.filters
