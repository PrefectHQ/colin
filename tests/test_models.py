"""Tests for Colin Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from colin.models import (
    CacheConfig,
    ColinConfig,
    ColinDocument,
    CompiledDocument,
    DocumentMeta,
    Frontmatter,
    LLMCall,
    Manifest,
    OutputConfig,
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


class TestOutputConfig:
    def test_defaults(self) -> None:
        config = OutputConfig()
        assert config.format == "markdown"
        assert config.path is None
        assert config.publish is None

    def test_should_publish_explicit_true_overrides_underscore(self) -> None:
        """Explicit publish=True makes even underscore-prefixed files public."""
        config = OutputConfig(publish=True)
        assert config.should_publish("project://_private.md") is True

    def test_should_publish_explicit_false_overrides_public_name(self) -> None:
        """Explicit publish=False makes even normal files private."""
        config = OutputConfig(publish=False)
        assert config.should_publish("project://public.md") is False

    def test_should_publish_underscore_file_is_private(self) -> None:
        """Files with _ prefix default to private (not published)."""
        config = OutputConfig()
        assert config.should_publish("project://_helper.md") is False

    def test_should_publish_normal_file_is_public(self) -> None:
        """Files without _ prefix default to public (published)."""
        config = OutputConfig()
        assert config.should_publish("project://public.md") is True

    def test_should_publish_underscore_directory_is_private(self) -> None:
        """Files in _ prefixed directories are private."""
        config = OutputConfig()
        assert config.should_publish("project://_partials/intro.md") is False

    def test_should_publish_nested_underscore_directory_is_private(self) -> None:
        """Files in nested _ prefixed directories are private."""
        config = OutputConfig()
        assert config.should_publish("project://chapters/_drafts/chapter1.md") is False

    def test_should_publish_handles_uri_without_scheme(self) -> None:
        """should_publish handles paths without scheme prefix."""
        config = OutputConfig()
        assert config.should_publish("_private.md") is False
        assert config.should_publish("public.md") is True

    def test_path_validation_rejects_absolute_path(self) -> None:
        """Absolute paths are rejected."""
        with pytest.raises(ValidationError, match="must be relative"):
            OutputConfig(path="/etc/passwd")

    def test_path_validation_rejects_parent_escape(self) -> None:
        """Paths with .. are rejected."""
        with pytest.raises(ValidationError, match="cannot contain"):
            OutputConfig(path="../escape.json")

        with pytest.raises(ValidationError, match="cannot contain"):
            OutputConfig(path="foo/../../../escape.json")

    def test_path_validation_accepts_relative_subdirs(self) -> None:
        """Relative paths with subdirectories are accepted."""
        config = OutputConfig(path="reports/daily/summary.json")
        assert config.path == "reports/daily/summary.json"


class TestColinConfig:
    def test_defaults(self) -> None:
        config = ColinConfig()
        assert config.output.format == "markdown"
        assert config.output.path is None
        assert config.output.publish is None
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
        with pytest.raises(ValidationError):
            CacheConfig(expires="invalid")

        with pytest.raises(ValidationError):
            CacheConfig(expires="1x")  # Invalid unit

        with pytest.raises(ValidationError):
            CacheConfig(expires="h1")  # Wrong order

        with pytest.raises(ValidationError):
            CacheConfig(expires="")  # Empty string

    def test_custom_values(self) -> None:
        config = ColinConfig(output=OutputConfig(format="skill"))
        assert config.output.format == "skill"

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
        assert fm.colin.output.format == "markdown"
        assert fm.colin.output.path is None
        assert fm.colin.output.publish is None
        assert fm.colin.cache.policy == "auto"
        assert fm.metadata == {}

    def test_with_metadata(self) -> None:
        fm = Frontmatter(
            colin=ColinConfig(output=OutputConfig(format="skill")),
            metadata={"name": "test", "description": "A test document"},
        )
        assert fm.colin.output.format == "skill"
        assert fm.colin.output.path is None
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

    def test_is_published_defaults_true(self) -> None:
        meta = DocumentMeta(uri="test", source_hash="abc")
        assert meta.is_published is True

    def test_migrate_is_private_true(self) -> None:
        """Old manifests with is_private=True should become is_published=False."""
        data = {"uri": "test", "source_hash": "abc", "is_private": True}
        meta = DocumentMeta.model_validate(data)
        assert meta.is_published is False

    def test_migrate_is_private_false(self) -> None:
        """Old manifests with is_private=False should become is_published=True."""
        data = {"uri": "test", "source_hash": "abc", "is_private": False}
        meta = DocumentMeta.model_validate(data)
        assert meta.is_published is True

    def test_ignores_unknown_fields(self) -> None:
        """DocumentMeta should ignore unknown fields from old manifests."""
        data = {"uri": "test", "source_hash": "abc", "unknown_field": "value"}
        meta = DocumentMeta.model_validate(data)
        assert meta.uri == "test"
        assert not hasattr(meta, "unknown_field")


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
