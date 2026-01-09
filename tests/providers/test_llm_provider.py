"""Tests for LLM provider functions."""

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from colin.compiler.cache import set_compile_context
from colin.compiler.context import CompileContext
from colin.models import DocumentMeta, LLMCall, Manifest
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


class TestPreviousOutput:
    """Tests for previous_output feature with position-based IDs."""

    async def test_complete_receives_previous_output_with_cache_id(self, tmp_path) -> None:
        """Test that _complete receives previous_output when using stable _cache_id.

        When a position-based _cache_id is provided, the LLM call should look up
        the previous output from the manifest and include it in the prompt.
        """
        captured_prompts: list[str] = []

        def capture_prompt(messages, info):
            # Capture the prompt for inspection
            captured_prompts.append(str(messages[0].parts[0].content))
            return ModelResponse(parts=[TextPart(content="New response")])

        provider = LLMProvider(model=FunctionModel(capture_prompt))

        # Create manifest with a previous LLM call recorded
        # Note: config_hash must match provider's _config_hash for previous_output to work
        manifest = Manifest()
        doc_uri = "project://test.md"
        doc_meta = DocumentMeta(
            uri=doc_uri,
            source_hash="abc123",
            llm_calls={
                "llm.complete:llm_1_5": LLMCall(
                    call_id="llm.complete:llm_1_5",
                    config_hash=provider._config_hash,  # Must match current config
                    input_hash="old_hash",
                    output_hash="out_hash",
                    output="Previous haiku output",
                    model="test",
                )
            },
        )
        manifest.set_document(doc_uri, doc_meta)

        project_provider = ProjectProvider(base_path=tmp_path)
        compile_ctx = CompileContext(
            manifest=manifest,
            document_uri=doc_uri,
            project_provider=project_provider,
        )

        set_compile_context(compile_ctx)
        try:
            # Call with position-based _cache_id that matches stored call
            result = await provider._complete(
                "Write a haiku about spring",
                _cache_id="llm_1_5",
            )
        finally:
            set_compile_context(None)

        assert result == "New response"
        # The prompt should include the previous output section
        assert len(captured_prompts) == 1
        assert "## Previous Output (for reference)" in captured_prompts[0]
        assert "Previous haiku output" in captured_prompts[0]
        assert "UseExisting" in captured_prompts[0]

    async def test_complete_no_previous_output_on_first_run(self, tmp_path) -> None:
        """Test that _complete doesn't include previous_output on first run.

        When there's no previous LLM call stored, the prompt should not
        include the previous output section.
        """
        captured_prompts: list[str] = []

        def capture_prompt(messages, info):
            captured_prompts.append(str(messages[0].parts[0].content))
            return ModelResponse(parts=[TextPart(content="First response")])

        provider = LLMProvider(model=FunctionModel(capture_prompt))

        # Empty manifest - no previous calls
        manifest = Manifest()
        doc_uri = "project://test.md"

        project_provider = ProjectProvider(base_path=tmp_path)
        compile_ctx = CompileContext(
            manifest=manifest,
            document_uri=doc_uri,
            project_provider=project_provider,
        )

        set_compile_context(compile_ctx)
        try:
            result = await provider._complete(
                "Write a haiku about spring",
                _cache_id="llm_1_5",
            )
        finally:
            set_compile_context(None)

        assert result == "First response"
        # The prompt should NOT include previous output section
        assert len(captured_prompts) == 1
        assert "## Previous Output" not in captured_prompts[0]
        assert "UseExisting" not in captured_prompts[0]

    async def test_complete_no_previous_output_without_cache_id(self, tmp_path) -> None:
        """Test that previous_output lookup requires _cache_id.

        When no _cache_id is provided (hash-based ID), previous_output
        is not looked up since the call_id won't be stable.
        """
        captured_prompts: list[str] = []

        def capture_prompt(messages, info):
            captured_prompts.append(str(messages[0].parts[0].content))
            return ModelResponse(parts=[TextPart(content="New response")])

        provider = LLMProvider(model=FunctionModel(capture_prompt))

        manifest = Manifest()
        doc_uri = "project://test.md"
        project_provider = ProjectProvider(base_path=tmp_path)
        compile_ctx = CompileContext(
            manifest=manifest,
            document_uri=doc_uri,
            project_provider=project_provider,
        )

        set_compile_context(compile_ctx)
        try:
            # Call WITHOUT _cache_id - uses hash-based ID
            result = await provider._complete("Write a haiku about spring")
        finally:
            set_compile_context(None)

        assert result == "New response"
        # The prompt should NOT include previous output section
        assert len(captured_prompts) == 1
        assert "## Previous Output" not in captured_prompts[0]

    async def test_complete_skips_failed_previous_output(self, tmp_path) -> None:
        """Test that failed previous LLM calls are not used for previous_output.

        If the previous call failed (is_successful=False), it should not
        be used as previous_output.
        """
        captured_prompts: list[str] = []

        def capture_prompt(messages, info):
            captured_prompts.append(str(messages[0].parts[0].content))
            return ModelResponse(parts=[TextPart(content="New response")])

        provider = LLMProvider(model=FunctionModel(capture_prompt))

        # Manifest with a FAILED previous call
        manifest = Manifest()
        doc_uri = "project://test.md"
        doc_meta = DocumentMeta(
            uri=doc_uri,
            source_hash="abc123",
            llm_calls={
                "llm.complete:llm_1_5": LLMCall(
                    call_id="llm.complete:llm_1_5",
                    config_hash=provider._config_hash,
                    input_hash="old_hash",
                    output_hash="",
                    output="",
                    model="test",
                    is_successful=False,  # Failed!
                    error="Some error",
                )
            },
        )
        manifest.set_document(doc_uri, doc_meta)

        project_provider = ProjectProvider(base_path=tmp_path)
        compile_ctx = CompileContext(
            manifest=manifest,
            document_uri=doc_uri,
            project_provider=project_provider,
        )

        set_compile_context(compile_ctx)
        try:
            result = await provider._complete(
                "Write a haiku about spring",
                _cache_id="llm_1_5",
            )
        finally:
            set_compile_context(None)

        assert result == "New response"
        # Failed calls should NOT be used as previous output
        assert len(captured_prompts) == 1
        assert "## Previous Output" not in captured_prompts[0]

    async def test_complete_skips_previous_output_when_config_changes(self, tmp_path) -> None:
        """Test that previous_output is NOT used when provider config changes.

        If the stored LLMCall has a different config_hash than the current
        provider, previous_output should not be used.
        """
        captured_prompts: list[str] = []

        def capture_prompt(messages, info):
            captured_prompts.append(str(messages[0].parts[0].content))
            return ModelResponse(parts=[TextPart(content="New response")])

        provider = LLMProvider(model=FunctionModel(capture_prompt))

        # Manifest with a call that has DIFFERENT config_hash
        manifest = Manifest()
        doc_uri = "project://test.md"
        doc_meta = DocumentMeta(
            uri=doc_uri,
            source_hash="abc123",
            llm_calls={
                "llm.complete:llm_1_5": LLMCall(
                    call_id="llm.complete:llm_1_5",
                    config_hash="different_config_hash",  # Different from provider!
                    input_hash="old_hash",
                    output_hash="out_hash",
                    output="Previous output from different config",
                    model="test",
                )
            },
        )
        manifest.set_document(doc_uri, doc_meta)

        project_provider = ProjectProvider(base_path=tmp_path)
        compile_ctx = CompileContext(
            manifest=manifest,
            document_uri=doc_uri,
            project_provider=project_provider,
        )

        set_compile_context(compile_ctx)
        try:
            result = await provider._complete(
                "Write a haiku about spring",
                _cache_id="llm_1_5",
            )
        finally:
            set_compile_context(None)

        assert result == "New response"
        # Previous output should NOT be used because config_hash doesn't match
        assert len(captured_prompts) == 1
        assert "## Previous Output" not in captured_prompts[0]
        assert "different config" not in captured_prompts[0]

    async def test_extract_receives_previous_output_with_cache_id(self, tmp_path) -> None:
        """Test that _extract receives previous_output when _cache_id is provided."""
        captured_prompts: list[str] = []

        def capture_prompt(messages, info):
            captured_prompts.append(str(messages[0].parts[0].content))
            return ModelResponse(parts=[TextPart(content="New extraction")])

        provider = LLMProvider(model=FunctionModel(capture_prompt))

        # Manifest with previous successful extract call
        manifest = Manifest()
        doc_uri = "project://test.md"
        doc_meta = DocumentMeta(
            uri=doc_uri,
            source_hash="abc123",
            llm_calls={
                "llm.extract:extract_1": LLMCall(
                    call_id="llm.extract:extract_1",
                    config_hash=provider._config_hash,
                    input_hash="old_hash",
                    output_hash="out_hash",
                    output="Previous extraction result",
                    model="test",
                )
            },
        )
        manifest.set_document(doc_uri, doc_meta)

        project_provider = ProjectProvider(base_path=tmp_path)
        compile_ctx = CompileContext(
            manifest=manifest,
            document_uri=doc_uri,
            project_provider=project_provider,
        )

        set_compile_context(compile_ctx)
        try:
            result = await provider._extract(
                "Some content to extract from",
                "key points",
                _cache_id="extract_1",
            )
        finally:
            set_compile_context(None)

        assert result == "New extraction"
        # The prompt should include previous output
        assert len(captured_prompts) == 1
        assert "## Previous Output" in captured_prompts[0]
        assert "Previous extraction result" in captured_prompts[0]

    async def test_classify_receives_previous_output_with_cache_id(self, tmp_path) -> None:
        """Test that _classify receives previous_output when _cache_id is provided."""
        captured_prompts: list[str] = []

        def capture_prompt(messages, info):
            captured_prompts.append(str(messages[0].parts[0].content))
            # Return valid JSON for classification
            return ModelResponse(parts=[TextPart(content='{"label": "positive"}')])

        provider = LLMProvider(model=FunctionModel(capture_prompt))

        # Manifest with previous successful classify call
        manifest = Manifest()
        doc_uri = "project://test.md"
        doc_meta = DocumentMeta(
            uri=doc_uri,
            source_hash="abc123",
            llm_calls={
                "llm.classify:classify_1": LLMCall(
                    call_id="llm.classify:classify_1",
                    config_hash=provider._config_hash,
                    input_hash="old_hash",
                    output_hash="out_hash",
                    output="positive",
                    model="test",
                )
            },
        )
        manifest.set_document(doc_uri, doc_meta)

        project_provider = ProjectProvider(base_path=tmp_path)
        compile_ctx = CompileContext(
            manifest=manifest,
            document_uri=doc_uri,
            project_provider=project_provider,
        )

        set_compile_context(compile_ctx)
        try:
            result = await provider._classify(
                "This is great!",
                ["positive", "negative"],
                _cache_id="classify_1",
            )
        finally:
            set_compile_context(None)

        assert result == "positive"
        # The prompt should include previous output
        assert len(captured_prompts) == 1
        assert "## Previous Output" in captured_prompts[0]
        assert "positive" in captured_prompts[0]
