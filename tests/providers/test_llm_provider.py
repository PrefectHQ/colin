"""Tests for LLM provider functions."""

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from colin.compiler.cache import set_compile_context
from colin.compiler.context import CompileContext
from colin.models import Manifest
from colin.providers.llm import LLMProvider
from colin.providers.project import ProjectProvider


class TestLLMProvider:
    @pytest.fixture
    def provider(self) -> LLMProvider:
        """Provider configured to use TestModel."""
        return LLMProvider(model="test")

    @pytest.fixture
    def compile_ctx(self, tmp_path) -> CompileContext:
        project_provider = ProjectProvider(base_path=tmp_path)
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
        self, provider: LLMProvider, compile_ctx: CompileContext
    ) -> None:
        """Test that extract returns a result using TestModel."""
        set_compile_context(compile_ctx)
        try:
            result = await provider._extract("content", "prompt")
        finally:
            set_compile_context(None)

        # TestModel returns a string result
        assert isinstance(result, str)

    async def test_extract_records_llm_call(
        self, provider: LLMProvider, compile_ctx: CompileContext
    ) -> None:
        """Test that extract records the LLM call in context."""
        set_compile_context(compile_ctx)
        try:
            await provider._extract("content", "prompt")
        finally:
            set_compile_context(None)

        assert len(compile_ctx.llm_calls) == 1

    async def test_extract_uses_cache(
        self, provider: LLMProvider, compile_ctx: CompileContext
    ) -> None:
        """Test that extract uses cache on second call with same inputs."""
        set_compile_context(compile_ctx)
        try:
            result1 = await provider._extract("content", "prompt")
            result2 = await provider._extract("content", "prompt")
        finally:
            set_compile_context(None)

        assert result1 == result2
        # Only one LLM call should be recorded due to caching
        assert len(compile_ctx.llm_calls) == 1

    async def test_extract_bypasses_cache_when_disabled(
        self, provider: LLMProvider, compile_ctx: CompileContext
    ) -> None:
        """Test that _cache=False bypasses the cache."""
        set_compile_context(compile_ctx)
        try:
            await provider._extract("content", "prompt", _cache=False)
            await provider._extract("content", "prompt", _cache=False)
        finally:
            set_compile_context(None)

        # Cache should not be populated when bypassed
        assert len(compile_ctx.manifest.cache) == 0
        # LLM call is still recorded (last one with same call_id)
        assert len(compile_ctx.llm_calls) == 1

    async def test_extract_records_failure(self, compile_ctx: CompileContext) -> None:
        """Test that extract records failed LLM calls with is_successful=False."""

        def failing_model(messages, info):
            raise RuntimeError("LLM error")

        provider = LLMProvider(model=FunctionModel(failing_model))

        set_compile_context(compile_ctx)
        try:
            with pytest.raises(RuntimeError, match="LLM error"):
                await provider._extract("content", "prompt")
        finally:
            set_compile_context(None)

        # Should have recorded the failed call
        assert len(compile_ctx.llm_calls) == 1
        llm_call = list(compile_ctx.llm_calls.values())[0]
        assert llm_call.is_successful is False
        assert llm_call.error == "LLM error"

    async def test_extract_failure_not_cached(self, compile_ctx: CompileContext) -> None:
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
                await provider._extract("content", "prompt")

            # Second call with same inputs should NOT use cache (failures not cached)
            result = await provider._extract("content", "prompt")
            assert result == "success"
        finally:
            set_compile_context(None)

        # Model should be called twice - failure wasn't cached
        assert call_count == 2

    def test_instructions_validation_both_set(self) -> None:
        """Test that setting both instructions and instructions_ref raises error."""
        with pytest.raises(
            ValueError, match="Cannot set both 'instructions' and 'instructions_ref'"
        ):
            LLMProvider(
                model="test",
                instructions="Be helpful",
                instructions_ref="prompts/analyst.md",
            )

    def test_instructions_can_be_set(self) -> None:
        """Test that instructions can be set as inline string."""
        provider = LLMProvider(model="test", instructions="You are a helpful assistant")
        assert provider.instructions == "You are a helpful assistant"
        assert provider.instructions_ref is None

    def test_instructions_ref_can_be_set(self) -> None:
        """Test that instructions_ref can be set as path."""
        provider = LLMProvider(model="test", instructions_ref="prompts/analyst.md")
        assert provider.instructions_ref == "prompts/analyst.md"
        assert provider.instructions is None

    async def test_extract_with_provider_instructions(
        self, compile_ctx: CompileContext, tmp_path
    ) -> None:
        """Test that extract uses provider-level instructions."""
        provider = LLMProvider(model="test", instructions="Be concise and helpful")

        set_compile_context(compile_ctx)
        try:
            result = await provider._extract("content", "prompt")
        finally:
            set_compile_context(None)

        # Should work without error
        assert isinstance(result, str)

    async def test_extract_with_call_level_instructions(self, compile_ctx: CompileContext) -> None:
        """Test that call-level instructions override provider-level."""
        provider = LLMProvider(model="test", instructions="Provider instructions")

        set_compile_context(compile_ctx)
        try:
            result = await provider._extract(
                "content", "prompt", instructions="Call-level instructions"
            )
        finally:
            set_compile_context(None)

        # Should work without error
        assert isinstance(result, str)

    async def test_extract_with_instructions_ref(
        self, compile_ctx: CompileContext, tmp_path
    ) -> None:
        """Test that instructions_ref resolves via ref() at runtime."""
        # Create a file that will be referenced
        instructions_file = tmp_path / "prompts" / "analyst.md"
        instructions_file.parent.mkdir(parents=True, exist_ok=True)
        instructions_file.write_text("You are a senior analyst.")

        # Update compile_ctx to use the tmp_path
        project_provider = ProjectProvider(base_path=tmp_path)
        compile_ctx.project_provider = project_provider

        # Create a compiled document entry for the instructions file
        from colin.models import CompiledDocument, Frontmatter

        compiled_doc = CompiledDocument(
            uri="project://prompts/analyst.md",
            frontmatter=Frontmatter(),
            output="You are a senior analyst.",
            output_path="prompts/analyst.md",
            source_hash="test",
            output_hash="test",
            refs=[],
            ref_versions={},
            llm_calls={},
            total_cost_usd=0.0,
        )
        compile_ctx.compiled_outputs["prompts/analyst.md"] = compiled_doc

        provider = LLMProvider(model="test", instructions_ref="prompts/analyst.md")

        set_compile_context(compile_ctx)
        try:
            result = await provider._extract("content", "prompt")
        finally:
            set_compile_context(None)

        # Should work without error
        assert isinstance(result, str)

    async def test_extract_instructions_in_cache_key(
        self, provider: LLMProvider, compile_ctx: CompileContext
    ) -> None:
        """Test that different instructions create different cache entries."""
        set_compile_context(compile_ctx)
        try:
            # First call with instructions
            await provider._extract("content", "prompt", instructions="Be concise")
            # Second call with different instructions
            await provider._extract("content", "prompt", instructions="Be detailed")
        finally:
            set_compile_context(None)

        # Different instructions should create different cache entries
        assert len(compile_ctx.manifest.cache) == 2

    async def test_classify_with_instructions(self, compile_ctx: CompileContext) -> None:
        """Test that classify accepts instructions parameter."""
        provider = LLMProvider(model="test", instructions="Be helpful")

        set_compile_context(compile_ctx)
        try:
            result = await provider._classify("content", ["yes", "no"], instructions="Be concise")
        finally:
            set_compile_context(None)

        assert isinstance(result, (str, bool))

    async def test_complete_with_instructions(self, compile_ctx: CompileContext) -> None:
        """Test that complete accepts instructions parameter."""
        provider = LLMProvider(model="test", instructions="Be helpful")

        set_compile_context(compile_ctx)
        try:
            result = await provider._complete("Write a haiku", instructions="Be creative")
        finally:
            set_compile_context(None)

        assert isinstance(result, str)

    async def test_resolve_instructions_without_context(self) -> None:
        """Test that resolving instructions_ref without compile context raises error."""
        provider = LLMProvider(model="test", instructions_ref="prompts/analyst.md")

        with pytest.raises(
            RuntimeError, match="Cannot resolve instructions_ref.*without compile context"
        ):
            await provider._resolve_instructions()

    async def test_resolve_instructions_precedence(self, compile_ctx: CompileContext) -> None:
        """Test that call-level instructions take precedence over provider-level."""
        provider = LLMProvider(model="test", instructions="Provider instructions")

        set_compile_context(compile_ctx)
        try:
            # Call-level should win
            resolved = await provider._resolve_instructions("Call-level instructions")
            assert resolved == "Call-level instructions"

            # Provider-level should be used when call-level is None
            resolved = await provider._resolve_instructions(None)
            assert resolved == "Provider instructions"
        finally:
            set_compile_context(None)
