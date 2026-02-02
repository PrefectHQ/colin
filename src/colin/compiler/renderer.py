"""Standalone template renderer with full Colin extension and provider support.

Extracts the rendering core from CompileEngine so it can be used independently
of the project/DAG/file-system orchestration. External consumers (e.g., a
knowledge graph system) can render templates with providers, LLM blocks,
sections, and ref tracking without needing a colin.toml project.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from colin.compiler.cache import set_compile_context
from colin.compiler.context import CompileContext, RefResolver
from colin.compiler.extensions.defer_block import DEFER_END_MARKER, DEFER_START_MARKER
from colin.compiler.jinja_env import bind_context_to_environment, create_jinja_environment
from colin.compiler.rendered import RenderedOutput
from colin.compiler.section_parser import parse_sections, remove_section_and_defer_markers
from colin.models import LLMCall, Manifest, Ref

if TYPE_CHECKING:
    from colin.api.project import ProjectConfig
    from colin.compiler.extensions.file_block import FileOutput
    from colin.compiler.state import OperationState
    from colin.models import CompiledDocument
    from colin.providers.manager import ProviderManager
    from colin.providers.project import ProjectProvider


@dataclass
class TemplateRenderResult:
    """Result of rendering a single template.

    Contains everything the rendering produced, without project-level metadata
    (uri, frontmatter, source_hash, output_path, output_hash). The orchestrator
    adds those when constructing a CompiledDocument or updating a graph node.
    """

    content: str
    """Rendered template output (after marker cleanup, before format conversion)."""

    refs: list[Ref] = field(default_factory=list)
    """Dependencies discovered during rendering."""

    ref_versions: dict[str, str] = field(default_factory=dict)
    """Version of each ref at render time (ref.key() -> version)."""

    llm_calls: dict[str, LLMCall] = field(default_factory=dict)
    """LLM calls made during rendering."""

    total_cost_usd: float = 0.0
    """Total cost of LLM calls."""

    sections: dict[str, str] = field(default_factory=dict)
    """Named sections extracted via {% section %} blocks."""

    file_outputs: dict[str, FileOutput] = field(default_factory=dict)
    """Files created via {% file %} blocks (path -> FileOutput)."""


class TemplateRenderer:
    """Renders a single Jinja template with Colin extensions and providers.

    This is the rendering layer extracted from CompileEngine. It handles:
    - Jinja environment with all Colin extensions ({% llm %}, {% file %}, etc.)
    - Provider namespace (colin.* functions)
    - Ref tracking for dependency detection
    - Two-pass rendering (first pass + defer blocks)
    - Section extraction

    It does NOT handle:
    - Document discovery or file I/O
    - Dependency graph or compilation ordering
    - Manifest persistence or staleness checking
    - Format rendering (JSON/YAML conversion)
    - Output writing or publishing

    Usage::

        async with create_provider_manager(config) as pm:
            renderer = TemplateRenderer(pm)
            result = await renderer.render("Hello {{ ref(colin.http.get('...')).content }}")
    """

    def __init__(self, provider_manager: ProviderManager) -> None:
        self.provider_manager = provider_manager

    async def render(
        self,
        template: str,
        *,
        document_uri: str = "",
        output_format: str = "markdown",
        manifest: Manifest | None = None,
        compiled_outputs: dict[str, CompiledDocument] | None = None,
        project_provider: ProjectProvider | None = None,
        config: ProjectConfig | None = None,
        ref_resolver: RefResolver | None = None,
        doc_state: OperationState | None = None,
    ) -> TemplateRenderResult:
        """Render a template with the full Colin extension and provider system.

        For standalone rendering (no project), use ``ref_resolver`` for string
        refs. Without a ``ref_resolver``, string refs require ``project_provider``
        and ``compiled_outputs``. The ``output()`` function returns None without
        ``config`` — templates should guard with ``{% if output() %}``.

        Args:
            template: Jinja template string to render.
            document_uri: URI identifying this template (for caching and output()).
            output_format: Output format hint (e.g., "markdown", "json").
            manifest: Manifest for caching. Defaults to empty (no cache).
            compiled_outputs: Already-compiled documents for project ref resolution.
                Requires project_provider.
            project_provider: Provider for reading compiled outputs from storage.
            config: Project configuration for output() path resolution.
            ref_resolver: Custom resolver for string refs. When set, string refs
                are delegated to this instead of compiled_outputs/project_provider.
            doc_state: Optional state for progress tracking.

        Returns:
            TemplateRenderResult with rendered content, tracked refs, LLM calls,
            sections, and file outputs.
        """
        env = create_jinja_environment()

        context = CompileContext(
            manifest=manifest,
            document_uri=document_uri,
            project_provider=project_provider,
            config=config,
            output_format=output_format,
            compiled_outputs=compiled_outputs,
            doc_state=doc_state,
            ref_resolver=ref_resolver,
        )

        bind_context_to_environment(
            env,
            context,
            provider_manager=self.provider_manager,
        )

        jinja_template = env.from_string(template)

        set_compile_context(context)
        try:
            # FIRST PASS: Render template (defer blocks emit markers)
            context.defer_blocks = {}
            raw_output = await jinja_template.render_async()

            # Extract sections from first pass
            first_pass_sections = parse_sections(raw_output)
            context.sections = first_pass_sections

            # SECOND PASS: If defer blocks exist, render them with first-pass context
            if context.defer_blocks:
                rendered = RenderedOutput(
                    content=raw_output,
                    sections=first_pass_sections,
                    output_format=output_format,
                )

                defer_outputs = {}
                for defer_id, caller in context.defer_blocks.items():
                    defer_content = await caller(rendered)
                    defer_outputs[defer_id] = defer_content

                final_output = _merge_defer_blocks(raw_output, defer_outputs)
                context.sections = parse_sections(final_output)
            else:
                final_output = raw_output

            # Remove section and defer markers, keep item markers for format renderers
            clean_output = remove_section_and_defer_markers(final_output)
        finally:
            set_compile_context(None)

        return TemplateRenderResult(
            content=clean_output,
            refs=context.refs,
            ref_versions=context.ref_versions,
            llm_calls=context.llm_calls,
            total_cost_usd=context.total_cost,
            sections=context.sections,
            file_outputs=context.file_outputs,
        )


def _merge_defer_blocks(output: str, defer_outputs: dict[str, str]) -> str:
    """Replace defer markers with rendered defer block content.

    Args:
        output: First pass output with defer markers.
        defer_outputs: Map of defer_id to rendered defer content.

    Returns:
        Output with defer markers replaced by rendered content.
    """
    result = output
    for defer_id, defer_content in defer_outputs.items():
        marker_start = DEFER_START_MARKER.format(id=defer_id)
        marker_end = DEFER_END_MARKER.format(id=defer_id)
        pattern = f"{marker_start}{marker_end}"
        result = result.replace(pattern, defer_content)
    return result
