"""Tests for LLM provider functions."""

from datetime import datetime, timezone

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from colin.compiler.context import CompileContext
from colin.models import Manifest, RefResult
from colin.providers.cache import set_compile_context
from colin.providers.context import ProviderContext
from colin.providers.llm import LLMProvider
from colin.providers.project import ProjectProvider
from colin.providers.referenceable import Referenceable
from colin.providers.storage.file import FileStorage


class TestLLMProvider:
    @pytest.fixture
    def provider(self) -> LLMProvider:
        """Provider configured to use TestModel."""
        return LLMProvider(model="test")

    @pytest.fixture
    def provider_ctx(self) -> ProviderContext:
        async def fake_ref(target: str | Referenceable) -> RefResult:
            uri = target if isinstance(target, str) else target.uri
            return RefResult(
                name="ref",
                description=None,
                content="content",
                template="",
                updated=datetime.now(timezone.utc),
                uri=uri,
            )

        return ProviderContext(
            manifest=Manifest(),
            document_uri="project://test.md",
            doc_state=None,
            ref=fake_ref,
            track_ref=lambda _uri: None,
        )

    @pytest.fixture
    def compile_ctx(self, tmp_path) -> CompileContext:
        storage = FileStorage(base_path=tmp_path)
        project_provider = ProjectProvider(storage=storage)
        return CompileContext(
            manifest=Manifest(),
            document_uri="project://test.md",
            project_provider=project_provider,
        )

    def test_model_defaults_to_none(self) -> None:
        """Test that model defaults to None (uses settings at call time)."""
        provider = LLMProvider()
        assert provider.model is None

    def test_model_can_be_configured(self) -> None:
        """Test that model can be explicitly configured."""
        provider = LLMProvider(model="anthropic:claude-3-opus")
        assert provider.model == "anthropic:claude-3-opus"

    def test_get_functions_returns_all_methods(self, provider: LLMProvider) -> None:
        """Test that get_functions returns all LLM methods."""
        funcs = provider.get_functions()
        assert "extract" in funcs
        assert "classify" in funcs
        assert "complete" in funcs

    async def test_extract_returns_result(
        self, provider: LLMProvider, provider_ctx: ProviderContext, compile_ctx: CompileContext
    ) -> None:
        """Test that extract returns a result using TestModel."""
        set_compile_context(compile_ctx)
        try:
            result = await provider._extract(provider_ctx, "content", "prompt")
        finally:
            set_compile_context(None)

        # TestModel returns a string result
        assert isinstance(result, str)

    async def test_extract_records_llm_call(
        self, provider: LLMProvider, provider_ctx: ProviderContext, compile_ctx: CompileContext
    ) -> None:
        """Test that extract records the LLM call in context."""
        set_compile_context(compile_ctx)
        try:
            await provider._extract(provider_ctx, "content", "prompt")
        finally:
            set_compile_context(None)

        assert len(compile_ctx.llm_calls) == 1

    async def test_extract_uses_cache(
        self, provider: LLMProvider, provider_ctx: ProviderContext, compile_ctx: CompileContext
    ) -> None:
        """Test that extract uses cache on second call with same inputs."""
        set_compile_context(compile_ctx)
        try:
            result1 = await provider._extract(provider_ctx, "content", "prompt")
            result2 = await provider._extract(provider_ctx, "content", "prompt")
        finally:
            set_compile_context(None)

        assert result1 == result2
        # Only one LLM call should be recorded due to caching
        assert len(compile_ctx.llm_calls) == 1

    async def test_extract_bypasses_cache_when_disabled(
        self, provider: LLMProvider, provider_ctx: ProviderContext, compile_ctx: CompileContext
    ) -> None:
        """Test that _cache=False bypasses the cache."""
        set_compile_context(compile_ctx)
        try:
            await provider._extract(provider_ctx, "content", "prompt", _cache=False)
            await provider._extract(provider_ctx, "content", "prompt", _cache=False)
        finally:
            set_compile_context(None)

        # Cache should not be populated when bypassed
        assert len(compile_ctx.manifest.cache) == 0
        # LLM call is still recorded (last one with same call_id)
        assert len(compile_ctx.llm_calls) == 1

    async def test_extract_records_failure(
        self, provider_ctx: ProviderContext, compile_ctx: CompileContext
    ) -> None:
        """Test that extract records failed LLM calls with is_successful=False."""

        def failing_model(messages, info):
            raise RuntimeError("LLM error")

        provider = LLMProvider(model=FunctionModel(failing_model))

        set_compile_context(compile_ctx)
        try:
            with pytest.raises(RuntimeError, match="LLM error"):
                await provider._extract(provider_ctx, "content", "prompt")
        finally:
            set_compile_context(None)

        # Should have recorded the failed call
        assert len(compile_ctx.llm_calls) == 1
        llm_call = list(compile_ctx.llm_calls.values())[0]
        assert llm_call.is_successful is False
        assert llm_call.error == "LLM error"

    async def test_extract_failure_not_cached(
        self, provider_ctx: ProviderContext, compile_ctx: CompileContext
    ) -> None:
        """Test that failed LLM calls are not cached."""
        call_count = 0

        def failing_then_succeeding(messages, info):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("First call fails")
            return ModelResponse(parts=[TextPart(content="success")])

        provider = LLMProvider(model=FunctionModel(failing_then_succeeding))

        set_compile_context(compile_ctx)
        try:
            # First call fails
            with pytest.raises(RuntimeError, match="First call fails"):
                await provider._extract(provider_ctx, "content", "prompt")

            # Second call with same inputs should NOT use cache (failures not cached)
            result = await provider._extract(provider_ctx, "content", "prompt")
            assert result == "success"
        finally:
            set_compile_context(None)

        # Model should be called twice - failure wasn't cached
        assert call_count == 2
