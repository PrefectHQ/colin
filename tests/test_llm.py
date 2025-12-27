"""Tests for LLM providers."""

from __future__ import annotations

from colin.llm.stub import StubLLMProvider


class TestStubLLMProvider:
    async def test_complete_returns_result(self) -> None:
        provider = StubLLMProvider()
        result = await provider.complete("Test prompt")

        assert result.text is not None
        assert "[STUB LLM RESPONSE:" in result.text
        assert result.model == "stub"
        assert result.cost == 0.0

    async def test_complete_deterministic(self) -> None:
        provider = StubLLMProvider()
        result1 = await provider.complete("Test prompt")
        result2 = await provider.complete("Test prompt")

        assert result1.text == result2.text

    async def test_complete_different_prompts_different_output(self) -> None:
        provider = StubLLMProvider()
        result1 = await provider.complete("Prompt A")
        result2 = await provider.complete("Prompt B")

        assert result1.text != result2.text

    async def test_complete_includes_input_info(self) -> None:
        provider = StubLLMProvider()
        prompt = "This is a test prompt"
        result = await provider.complete(prompt)

        assert f"Input length: {len(prompt)} chars" in result.text

    async def test_complete_includes_model_name(self) -> None:
        provider = StubLLMProvider()
        result = await provider.complete("Test", model="gpt-4")

        assert "Model requested: gpt-4" in result.text

    async def test_extract_returns_result(self) -> None:
        provider = StubLLMProvider()
        result = await provider.extract("Content here", "Extract names")

        assert result.text is not None
        assert "[STUB EXTRACTION:" in result.text
        assert result.model == "stub"
        assert result.cost == 0.0

    async def test_extract_deterministic(self) -> None:
        provider = StubLLMProvider()
        result1 = await provider.extract("Content", "Extract")
        result2 = await provider.extract("Content", "Extract")

        assert result1.text == result2.text

    async def test_extract_includes_content_info(self) -> None:
        provider = StubLLMProvider()
        content = "This is the content to extract from"
        result = await provider.extract(content, "Extract names")

        assert f"Extracted from {len(content)} chars" in result.text

    async def test_extract_includes_prompt(self) -> None:
        provider = StubLLMProvider()
        result = await provider.extract("Content", "Extract all names")

        assert "Extract all names" in result.text

    async def test_extract_with_previous_output(self) -> None:
        provider = StubLLMProvider()
        result = await provider.extract(
            "Content",
            "Extract names",
            previous_output="Previous result",
        )

        assert "Previous output hash:" in result.text
