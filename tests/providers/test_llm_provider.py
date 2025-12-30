"""Tests for LLM provider functions."""

from datetime import datetime, timezone

from colin.models import Manifest, RefResult
from colin.providers.context import ProviderContext
from colin.providers.llm import LLMProvider
from colin.providers.referenceable import Referenceable


async def test_llm_provider_extract_serializes_refresult() -> None:
    """extract() passes serialized content to context."""
    captured: dict[str, object] = {}

    async def fake_extract(
        content: str, prompt: str, call_id: str | None, model: str | None
    ) -> str:
        captured["content"] = content
        captured["prompt"] = prompt
        captured["call_id"] = call_id
        captured["model"] = model
        return "ok"

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

    ctx = ProviderContext(
        manifest=Manifest(),
        document_uri="project://test.md",
        doc_state=None,
        ref=fake_ref,
        track_ref=lambda _uri: None,
        extract=fake_extract,
    )

    provider = LLMProvider()
    ref = RefResult(
        name="source",
        description=None,
        content="Hello world",
        template="",
        updated=datetime.now(timezone.utc),
        uri="project://source.md",
    )

    result = await provider._extract(ctx, ref, "summarize")

    assert result == "ok"
    # _serialize_for_llm adds metadata headers for RefResult
    expected_content = "# source\nURI: project://source.md\n\nHello world"
    assert captured["content"] == expected_content
    assert captured["prompt"] == "summarize"
