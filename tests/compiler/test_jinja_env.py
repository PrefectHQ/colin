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


def test_bind_context_sets_extract_alias(tmp_path: Path) -> None:
    """extract global points at providers.llm.extract."""
    storage = FileStorage(base_path=tmp_path)
    project_provider = ProjectProvider(storage)
    context = CompileContext(
        manifest=Manifest(),
        document_uri="project://test.md",
        default_model="anthropic:claude-haiku-3",
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
        extract=context.extract,
    )

    bind_context_to_environment(env, context, provider_manager, provider_ctx)

    providers = env.globals["providers"]
    assert env.globals["extract"] is getattr(getattr(providers, "llm"), "extract")
