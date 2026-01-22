"""Tests for Jinja environment bindings."""

from pathlib import Path

from colin.api.project import ProjectConfig
from colin.compiler.context import CompileContext
from colin.compiler.extensions.filters import create_llm_extract_filter
from colin.compiler.jinja_env import bind_context_to_environment, create_jinja_environment
from colin.models import Manifest
from colin.providers.http import HTTPProvider
from colin.providers.llm import LLMProvider
from colin.providers.manager import ProviderManager
from colin.providers.project import ProjectProvider


def test_bind_context_sets_colin_namespace(tmp_path: Path) -> None:
    """colin namespace exposes providers."""
    project_provider = ProjectProvider(base_path=tmp_path)
    config = ProjectConfig(
        name="test",
        project_root=tmp_path,
        model_path=tmp_path / "models",
        output_path=tmp_path / "output",
        manifest_path=tmp_path / ".colin" / "manifest.json",
    )
    context = CompileContext(
        manifest=Manifest(),
        document_uri="project://test.md",
        project_provider=project_provider,
        config=config,
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


async def test_llm_extract_filter_generates_position_based_ids(tmp_path: Path) -> None:
    """Test that llm_extract filter generates sequential position-based IDs.

    Each filter invocation gets a unique ID (extract_1, extract_2, etc.)
    which enables previous_output lookup across recompilations.
    """
    captured_position_ids: list[str | None] = []

    # Create a mock LLM namespace that captures _position_id
    class MockLLMNamespace:
        async def extract(
            self,
            content: object,
            prompt: str,
            model: str | None = None,
            instructions: str | None = None,
            _position_id: str | None = None,
            _cache: bool = True,
        ) -> str:
            captured_position_ids.append(_position_id)
            return f"extracted: {prompt}"

    llm_namespace = MockLLMNamespace()
    filter_func = create_llm_extract_filter(llm_namespace)

    # Create a mock Jinja context (filter uses @pass_context)
    class MockContext(dict):
        """Minimal mock for Jinja context."""

        pass

    mock_context = MockContext()

    # Call filter multiple times without explicit _cache_id
    # Note: @pass_context makes the first arg the Jinja context
    await filter_func(mock_context, "content1", "prompt1")
    await filter_func(mock_context, "content2", "prompt2")
    await filter_func(mock_context, "content3", "prompt3")

    # Should generate sequential IDs
    assert captured_position_ids == ["extract_1", "extract_2", "extract_3"]


async def test_llm_extract_filter_respects_explicit_cache_id(tmp_path: Path) -> None:
    """Test that explicit _cache_id overrides auto-generated ID."""
    captured_position_ids: list[str | None] = []

    class MockLLMNamespace:
        async def extract(
            self,
            content: object,
            prompt: str,
            model: str | None = None,
            instructions: str | None = None,
            _position_id: str | None = None,
            _cache: bool = True,
        ) -> str:
            captured_position_ids.append(_position_id)
            return f"extracted: {prompt}"

    llm_namespace = MockLLMNamespace()
    filter_func = create_llm_extract_filter(llm_namespace)

    # Create a mock Jinja context (filter uses @pass_context)
    class MockContext(dict):
        """Minimal mock for Jinja context."""

        pass

    mock_context = MockContext()

    # Mix of auto and explicit IDs
    # Note: @pass_context makes the first arg the Jinja context
    await filter_func(mock_context, "content1", "prompt1")  # auto
    await filter_func(mock_context, "content2", "prompt2", _cache_id="custom_id")  # explicit
    await filter_func(mock_context, "content3", "prompt3")  # auto continues

    # Explicit ID used, auto counter continues
    assert captured_position_ids == ["extract_1", "custom_id", "extract_3"]
