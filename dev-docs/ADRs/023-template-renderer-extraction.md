# ADR 023: Template Renderer Extraction

**Status**: Accepted
**Date**: 2026-02-02

## Context

Colin's compilation infrastructure — Jinja extensions, providers, LLM blocks, ref tracking, section extraction, two-pass defer rendering — lives inside `CompileEngine._compile_document()`. This couples the rendering core to the file-based project model: document discovery, DAG-based dependency ordering, manifest persistence, staleness checking, and output publishing.

External consumers need the rendering infrastructure without the orchestration. Colin-KG, for example, has its own materialization strategy that differs from Colin's DAG-based topological sort. It needs Colin's Jinja extensions, provider namespace, and ref tracking, but has its own strategy for deciding what to render and in what order.

## Decision

Extract `TemplateRenderer` from `CompileEngine._compile_document()` as a standalone class in `compiler/renderer.py`. It renders a single template string with the full extension and provider system and returns a `TemplateRenderResult` — a lightweight dataclass containing only rendering artifacts (content, refs, llm_calls, sections, file_outputs), not project-level metadata.

`CompileEngine` uses `TemplateRenderer` internally, then adds project metadata (uri, frontmatter, source_hash, output_path) and applies format rendering to construct a `CompiledDocument`.

Add a `RefResolver` protocol so consumers can inject custom ref resolution logic. Colin-KG can resolve refs from its graph; Colin's project model resolves from `compiled_outputs` and `ProjectProvider`. The renderer doesn't care which strategy is used.

```python
from colin.compiler import TemplateRenderer
from colin.providers.manager import create_provider_manager

async with create_provider_manager(config) as pm:
    renderer = TemplateRenderer(pm)
    result = await renderer.render(
        "Hello {{ ref(colin.http.get('https://example.com')).content }}",
        ref_resolver=my_graph_resolver,  # optional
    )
    # result.content, result.refs, result.llm_calls, result.sections, ...
```

## Consequences

- Colin's rendering is independently usable without a colin.toml project, manifest, or file system
- The orchestration strategy is decoupled from rendering
- `CompileEngine` becomes one orchestration strategy that happens to use `TemplateRenderer`
- `CompileContext` parameters (`manifest`, `project_provider`, `config`) are now optional — the renderer creates sensible defaults when they're absent
- `RefResolver` protocol enables custom ref resolution strategies
