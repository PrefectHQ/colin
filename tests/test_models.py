"""Tests for Colin Pydantic models."""

from __future__ import annotations

from colin.models import (
    CacheConfig,
    ColinConfig,
    ColinDocument,
    CompiledDocument,
    DocumentMeta,
    Frontmatter,
    LLMCall,
    Manifest,
    Ref,
)


class TestLLMCall:
    def test_creation(self) -> None:
        call = LLMCall(
            call_id="test-id",
            input_hash="abc123",
            output_hash="def456",
            output="test output",
            model="stub",
            cost_usd=0.01,
        )
        assert call.call_id == "test-id"
        assert call.input_hash == "abc123"
        assert call.output_hash == "def456"
        assert call.output == "test output"
        assert call.model == "stub"
        assert call.cost_usd == 0.01

    def test_created_at_default(self) -> None:
        call = LLMCall(
            call_id="test",
            input_hash="a",
            output_hash="b",
            output="x",
            model="stub",
        )
        assert call.created_at is not None
        assert call.created_at.tzinfo is not None


class TestColinConfig:
    def test_defaults(self) -> None:
        config = ColinConfig()
        assert config.output == "markdown"
        assert config.cache.policy == "auto"
        assert config.cache.expires is None
        assert config.storage is None

    def test_custom_cache_policy(self) -> None:
        config = ColinConfig(cache=CacheConfig(policy="always"))
        assert config.cache.policy == "always"

    def test_custom_cache_expires(self) -> None:
        config = ColinConfig(cache=CacheConfig(expires="1h"))
        assert config.cache.policy == "auto"
        assert config.cache.expires == "1h"

    def test_cache_expires_calendar_aligned(self) -> None:
        config = ColinConfig(cache=CacheConfig(expires="1cM"))
        assert config.cache.expires == "1cM"

    def test_cache_expires_validation(self) -> None:
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CacheConfig(expires="invalid")

        with pytest.raises(ValidationError):
            CacheConfig(expires="1x")  # Invalid unit

        with pytest.raises(ValidationError):
            CacheConfig(expires="h1")  # Wrong order

        with pytest.raises(ValidationError):
            CacheConfig(expires="")  # Empty string

    def test_custom_values(self) -> None:
        config = ColinConfig(output="skill")
        assert config.output == "skill"

    def test_cache_shorthand_syntax(self) -> None:
        """Accept 'cache: never' as shorthand for 'cache: {policy: never}'."""
        # Use model_validate to test the YAML shorthand syntax (cache: never)
        config = ColinConfig.model_validate({"cache": "never"})
        assert config.cache.policy == "never"
        assert config.cache.expires is None

        config = ColinConfig.model_validate({"cache": "always"})
        assert config.cache.policy == "always"

        config = ColinConfig.model_validate({"cache": "auto"})
        assert config.cache.policy == "auto"


class TestFrontmatter:
    def test_defaults(self) -> None:
        fm = Frontmatter()
        assert fm.colin.output == "markdown"
        assert fm.metadata == {}

    def test_with_metadata(self) -> None:
        fm = Frontmatter(
            colin=ColinConfig(output="skill"),
            metadata={"name": "test", "description": "A test document"},
        )
        assert fm.colin.output == "skill"
        assert fm.metadata["name"] == "test"


class TestDocumentMeta:
    def test_creation(self) -> None:
        meta = DocumentMeta(
            uri="context/test",
            source_hash="abc123",
        )
        assert meta.uri == "context/test"
        assert meta.source_hash == "abc123"
        assert meta.output_hash is None
        assert meta.compiled_at is None
        assert meta.refs == []
        assert meta.ref_versions == {}
        assert meta.llm_calls == {}


class TestManifest:
    def test_empty_manifest(self) -> None:
        manifest = Manifest()
        assert manifest.version == "1"
        assert manifest.documents == {}
        assert manifest.compiled_at is None

    def test_get_document_missing(self) -> None:
        manifest = Manifest()
        assert manifest.get_document("nonexistent") is None

    def test_set_and_get_document(self) -> None:
        manifest = Manifest()
        meta = DocumentMeta(
            uri="context/test",
            source_hash="abc123",
        )
        manifest.set_document("context/test", meta)
        assert manifest.get_document("context/test") == meta

    def test_get_dependents(self) -> None:
        manifest = Manifest()
        # Refs with project provider and path in args
        manifest.set_document(
            "context/a",
            DocumentMeta(
                uri="context/a",
                source_hash="a",
                refs=[
                    Ref(
                        provider="project", connection="", method="get", args={"path": "context/b"}
                    ),
                    Ref(
                        provider="project", connection="", method="get", args={"path": "context/c"}
                    ),
                ],
            ),
        )
        manifest.set_document(
            "context/d",
            DocumentMeta(
                uri="context/d",
                source_hash="d",
                refs=[
                    Ref(
                        provider="project", connection="", method="get", args={"path": "context/b"}
                    ),
                ],
            ),
        )

        dependents = manifest.get_dependents("project://context/b")
        assert set(dependents) == {"context/a", "context/d"}

    def test_get_llm_call(self) -> None:
        manifest = Manifest()
        call = LLMCall(
            call_id="call-1",
            input_hash="in",
            output_hash="out",
            output="result",
            model="stub",
        )
        manifest.set_document(
            "context/test",
            DocumentMeta(
                uri="context/test",
                source_hash="abc",
                llm_calls={"call-1": call},
            ),
        )

        assert manifest.get_llm_call("context/test", "call-1") == call
        assert manifest.get_llm_call("context/test", "nonexistent") is None
        assert manifest.get_llm_call("nonexistent", "call-1") is None


class TestColinDocument:
    def test_creation(self) -> None:
        doc = ColinDocument(
            uri="context/test",
            frontmatter=Frontmatter(),
            template_content="# Hello",
            source_hash="abc123",
        )
        assert doc.uri == "context/test"
        assert doc.template_content == "# Hello"


class TestCompiledDocument:
    def test_creation(self) -> None:
        doc = CompiledDocument(
            uri="context/test",
            frontmatter=Frontmatter(),
            output="# Hello",
            output_path="test.md",
            source_hash="abc123",
            output_hash="def456",
        )
        assert doc.uri == "context/test"
        assert doc.output == "# Hello"
        assert doc.output_path == "test.md"
        assert doc.source_hash == "abc123"
        assert doc.output_hash == "def456"
