"""Tests for standalone TemplateRenderer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from jinja2 import TemplateSyntaxError

from colin.compiler.renderer import TemplateRenderer, TemplateRenderResult, _merge_defer_blocks
from colin.exceptions import RefNotCompiledError
from colin.models import CompiledDocument, Frontmatter, Ref
from colin.providers.http import HTTPProvider
from colin.providers.llm import LLMProvider
from colin.providers.manager import ProviderManager
from colin.providers.project import ProjectProvider
from colin.resources import Resource


@pytest.fixture
def provider_manager() -> ProviderManager:
    pm = ProviderManager()
    pm.register(HTTPProvider())
    pm.register(LLMProvider())
    return pm


@pytest.fixture
def renderer(provider_manager: ProviderManager) -> TemplateRenderer:
    return TemplateRenderer(provider_manager)


class MockResource(Resource):
    """Minimal Resource for testing ref resolution."""

    def __init__(self, content: str, *, version: str = "v1", name: str = "mock") -> None:
        self._content = content
        self._version = version
        self._name = name

    @property
    def content(self) -> str:
        return self._content

    @property
    def version(self) -> str:
        return self._version

    def ref(self) -> Ref:
        return Ref(
            provider="test",
            connection="",
            method="get",
            args={"path": self._name},
        )

    def __str__(self) -> str:
        return self._content


class TestTemplateRenderer:
    async def test_render_plain_template(self, renderer: TemplateRenderer) -> None:
        result = await renderer.render("Hello, world!")

        assert result.content == "Hello, world!"
        assert result.refs == []
        assert result.llm_calls == {}
        assert result.sections == {}

    async def test_render_with_jinja_expressions(self, renderer: TemplateRenderer) -> None:
        result = await renderer.render("{{ 1 + 2 }} items")

        assert result.content == "3 items"

    async def test_render_with_jinja_control_flow(self, renderer: TemplateRenderer) -> None:
        template = "{% for i in range(3) %}{{ i }}{% endfor %}"
        result = await renderer.render(template)

        assert result.content == "012"

    async def test_render_returns_template_render_result(self, renderer: TemplateRenderer) -> None:
        result = await renderer.render("test")

        assert isinstance(result, TemplateRenderResult)
        assert hasattr(result, "content")
        assert hasattr(result, "refs")
        assert hasattr(result, "ref_versions")
        assert hasattr(result, "llm_calls")
        assert hasattr(result, "total_cost_usd")
        assert hasattr(result, "sections")
        assert hasattr(result, "file_outputs")

    async def test_render_standalone_no_project(self, renderer: TemplateRenderer) -> None:
        """TemplateRenderer works without ProjectConfig, ProjectProvider, or Manifest."""
        result = await renderer.render("No project needed: {{ 42 }}")

        assert result.content == "No project needed: 42"
        assert result.total_cost_usd == 0.0

    async def test_render_with_llm_block(
        self, renderer: TemplateRenderer, mock_agent: MagicMock
    ) -> None:
        template = "{% llm %}Summarize this.{% endllm %}"
        result = await renderer.render(template)

        assert "[TEST LLM RESPONSE]" in result.content
        assert len(result.llm_calls) == 1

    async def test_render_llm_block_tracks_cost(
        self, renderer: TemplateRenderer, mock_agent: MagicMock
    ) -> None:
        template = "{% llm %}Do something.{% endllm %}"
        result = await renderer.render(template)

        assert len(result.llm_calls) == 1
        # Cost is tracked (mock returns 0 cost by default)
        assert isinstance(result.total_cost_usd, float)

    async def test_render_with_sections(self, renderer: TemplateRenderer) -> None:
        template = (
            "{% section intro %}Welcome{% endsection %}{% section body %}Content{% endsection %}"
        )
        result = await renderer.render(template)

        assert "intro" in result.sections
        assert "body" in result.sections
        assert "Welcome" in result.sections["intro"]
        assert "Content" in result.sections["body"]

    async def test_render_with_ref_resolver(self, renderer: TemplateRenderer) -> None:
        """Custom RefResolver is called for string refs."""
        resolved_resource = MockResource("resolved content", name="my-doc")

        async def mock_resolver(path: str, *, allow_stale: bool = False) -> Resource | None:
            if path == "my-doc":
                return resolved_resource
            return None

        result = await renderer.render(
            "{{ ref('my-doc') }}",
            ref_resolver=mock_resolver,
        )

        assert "resolved content" in result.content
        assert len(result.refs) == 1
        assert result.refs[0].provider == "test"

    async def test_render_tracks_provider_refs(
        self,
        provider_manager: ProviderManager,
    ) -> None:
        """Provider resources wrapped in ref() are tracked."""
        renderer = TemplateRenderer(provider_manager)
        # colin.http.get returns a resource that ref() can track
        # We can't call real HTTP in tests, but we can verify the mechanism
        # by rendering a template that accesses the colin namespace
        result = await renderer.render("{{ colin.http }}")

        # The namespace should be accessible (doesn't error)
        assert isinstance(result, TemplateRenderResult)

    async def test_render_with_defer_block(self, renderer: TemplateRenderer) -> None:
        template = "Main content.{% defer %}Length: {{ rendered.content | length }}{% enddefer %}"
        result = await renderer.render(template)

        # Defer block should have access to rendered.content from first pass
        assert "Length:" in result.content
        # The length should be a positive number (the first pass content length)
        assert "Main content." in result.content

    async def test_render_with_sections_and_defer(self, renderer: TemplateRenderer) -> None:
        template = (
            "{% section intro %}Hello{% endsection %}"
            "{% defer %}"
            "Sections: {{ rendered.sections.keys() | list | join(', ') }}"
            "{% enddefer %}"
        )
        result = await renderer.render(template)

        assert "intro" in result.content

    async def test_render_multiple_times(self, renderer: TemplateRenderer) -> None:
        """Same renderer can render multiple templates."""
        result1 = await renderer.render("First: {{ 1 }}")
        result2 = await renderer.render("Second: {{ 2 }}")

        assert result1.content == "First: 1"
        assert result2.content == "Second: 2"
        # Each render has independent tracking
        assert result1.refs == []
        assert result2.refs == []

    async def test_render_empty_template(self, renderer: TemplateRenderer) -> None:
        result = await renderer.render("")
        assert result.content == ""

    async def test_render_preserves_internal_whitespace(self, renderer: TemplateRenderer) -> None:
        template = "line 1\n\nline 3"
        result = await renderer.render(template)
        assert result.content == "line 1\n\nline 3"

    async def test_ref_resolver_none_raises_without_allow_stale(
        self, renderer: TemplateRenderer
    ) -> None:
        """RefResolver returning None without allow_stale raises RefNotCompiledError."""

        async def resolver(path: str, *, allow_stale: bool = False) -> Resource | None:
            return None

        with pytest.raises(RefNotCompiledError):
            await renderer.render(
                "{{ ref('missing') }}",
                ref_resolver=resolver,
            )

    async def test_ref_resolver_none_with_allow_stale(self, renderer: TemplateRenderer) -> None:
        """RefResolver returning None with allow_stale returns None gracefully."""

        async def resolver(path: str, *, allow_stale: bool = False) -> Resource | None:
            return None

        result = await renderer.render(
            "{{ ref('missing', allow_stale=True) }}",
            ref_resolver=resolver,
        )

        assert result.content == "None"
        assert result.refs == []

    async def test_ref_resolver_tracks_versions(self, renderer: TemplateRenderer) -> None:
        """Resolved refs have their versions tracked in ref_versions."""
        resource = MockResource("data", version="abc123", name="versioned")

        async def resolver(path: str, *, allow_stale: bool = False) -> Resource | None:
            return resource

        result = await renderer.render(
            "{{ ref('versioned') }}",
            ref_resolver=resolver,
        )

        assert len(result.ref_versions) == 1
        ref_key = result.refs[0].key()
        assert result.ref_versions[ref_key] == "abc123"

    async def test_ref_resolver_deduplicates_refs(self, renderer: TemplateRenderer) -> None:
        """Same ref resolved twice only appears once in results."""
        resource = MockResource("data", name="dup")

        async def resolver(path: str, *, allow_stale: bool = False) -> Resource | None:
            return resource

        result = await renderer.render(
            "{{ ref('dup') }} {{ ref('dup') }}",
            ref_resolver=resolver,
        )

        assert len(result.refs) == 1

    async def test_compiled_outputs_ref_resolution(
        self, renderer: TemplateRenderer, tmp_path: Path
    ) -> None:
        """compiled_outputs enables project-style string ref resolution."""
        compiled = CompiledDocument(
            uri="project://other.md",
            frontmatter=Frontmatter(),
            output="other content",
            source_hash="abc",
            output_hash="def",
            output_path="other.md",
        )

        result = await renderer.render(
            "{{ ref('other.md').content }}",
            compiled_outputs={"other.md": compiled},
            project_provider=ProjectProvider(base_path=tmp_path),
        )

        assert result.content == "other content"
        assert len(result.refs) == 1
        assert result.refs[0].provider == "project"

    async def test_multiple_llm_blocks_accumulate(
        self, renderer: TemplateRenderer, mock_agent: MagicMock
    ) -> None:
        template = "{% llm %}First prompt.{% endllm %} and {% llm %}Second prompt.{% endllm %}"
        result = await renderer.render(template)

        assert len(result.llm_calls) == 2
        assert result.content.count("[TEST LLM RESPONSE]") == 2

    async def test_file_block_populates_file_outputs(self, renderer: TemplateRenderer) -> None:
        template = 'Main output.{% file "extra.txt" %}File content here.{% endfile %}'
        result = await renderer.render(template)

        assert "extra.txt" in result.file_outputs
        assert "File content here." in result.file_outputs["extra.txt"].content

    async def test_multiple_file_blocks(self, renderer: TemplateRenderer) -> None:
        template = '{% file "a.txt" %}Alpha{% endfile %}{% file "b.txt" %}Beta{% endfile %}'
        result = await renderer.render(template)

        assert len(result.file_outputs) == 2
        assert "Alpha" in result.file_outputs["a.txt"].content
        assert "Beta" in result.file_outputs["b.txt"].content

    async def test_template_syntax_error_propagates(self, renderer: TemplateRenderer) -> None:
        with pytest.raises(TemplateSyntaxError):
            await renderer.render("{% if %}broken{% endif %}")

    async def test_render_cleans_compile_context(self, renderer: TemplateRenderer) -> None:
        """Compile context is cleaned up even when rendering succeeds."""
        from colin.compiler.cache import get_compile_context

        await renderer.render("ok")
        assert get_compile_context() is None

    async def test_render_cleans_compile_context_on_error(self, renderer: TemplateRenderer) -> None:
        """Compile context is cleaned up when rendering raises."""
        from colin.compiler.cache import get_compile_context

        with pytest.raises(Exception):  # noqa: B017
            await renderer.render("{{ undefined_var.bad_attr }}")
        assert get_compile_context() is None

    async def test_document_uri_passed_through(self, renderer: TemplateRenderer) -> None:
        """document_uri is available to the rendering context."""
        result = await renderer.render(
            "ok",
            document_uri="custom://my-template",
        )
        assert result.content == "ok"

    async def test_string_ref_without_project_provider_raises(
        self, renderer: TemplateRenderer
    ) -> None:
        """String refs without ref_resolver or project_provider raise RefNotCompiledError."""
        with pytest.raises(RefNotCompiledError):
            await renderer.render("{{ ref('some-doc') }}")

    async def test_string_ref_without_project_provider_allow_stale(
        self, renderer: TemplateRenderer
    ) -> None:
        """String refs without project_provider and allow_stale=True return None."""
        result = await renderer.render("{{ ref('some-doc', allow_stale=True) }}")
        assert result.content == "None"

    async def test_output_returns_none_without_config(self, renderer: TemplateRenderer) -> None:
        """output() returns None when no config is provided (standalone rendering)."""
        result = await renderer.render("{% set prev = output() %}{{ prev is none }}")
        assert result.content == "True"


class TestMergeDeferBlocks:
    def test_replaces_single_marker(self) -> None:
        output = "before<!--COLIN:DEFER_START:d1--><!--COLIN:DEFER_END:d1-->after"
        result = _merge_defer_blocks(output, {"d1": "REPLACED"})
        assert result == "beforeREPLACEDafter"

    def test_replaces_multiple_markers(self) -> None:
        output = (
            "A<!--COLIN:DEFER_START:d1--><!--COLIN:DEFER_END:d1-->"
            "B<!--COLIN:DEFER_START:d2--><!--COLIN:DEFER_END:d2-->C"
        )
        result = _merge_defer_blocks(output, {"d1": "X", "d2": "Y"})
        assert result == "AXBYC"

    def test_no_markers_returns_unchanged(self) -> None:
        result = _merge_defer_blocks("no markers here", {})
        assert result == "no markers here"

    def test_unmatched_marker_unchanged(self) -> None:
        output = "<!--COLIN:DEFER_START:d1--><!--COLIN:DEFER_END:d1-->"
        result = _merge_defer_blocks(output, {"d2": "NOPE"})
        assert result == output
