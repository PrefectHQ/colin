"""Tests for Jinja environment bindings."""

from pathlib import Path

from colin.compiler.context import CompileContext
from colin.compiler.jinja_env import bind_context_to_environment, create_jinja_environment
from colin.models import Manifest
from colin.providers.context import ProviderContext
from colin.providers.http import HTTPProvider
from colin.providers.llm import LLMProvider
from colin.providers.manager import ProviderManager
from colin.providers.project import ProjectProvider
from colin.providers.storage.file import FileStorage


def test_bind_context_sets_llm_shortcut(tmp_path: Path) -> None:
    """llm global points at providers.llm."""
    storage = FileStorage(base_path=tmp_path)
    project_provider = ProjectProvider(storage)
    context = CompileContext(
        manifest=Manifest(),
        document_uri="project://test.md",
        project_provider=project_provider,
    )

    provider_manager = ProviderManager()
    provider_manager.register(HTTPProvider())
    provider_manager.register(LLMProvider())

    env = create_jinja_environment()
    provider_ctx = ProviderContext(
        manifest=context.manifest,
        document_uri=context.document_uri,
        doc_state=None,
        ref=context.ref,
        track_ref=context.track_ref,
    )

    bind_context_to_environment(env, context, provider_manager, provider_ctx)

    providers = env.globals["providers"]
    # llm is a shortcut to providers.llm
    assert env.globals["llm"] is getattr(providers, "llm")
    # llm_extract and llm_classify are filters
    assert "llm_extract" in env.filters
    assert "llm_classify" in env.filters
