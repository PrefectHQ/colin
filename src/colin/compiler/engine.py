"""Colin compilation engine."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from contextlib import nullcontext as _nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import frontmatter as fm_parser
from jinja2 import TemplateSyntaxError, nodes

from colin.compiler.cache import set_compile_context, set_used_cache_keys
from colin.compiler.context import CompileContext
from colin.compiler.graph import DependencyGraph
from colin.compiler.jinja_env import bind_context_to_environment, create_jinja_environment
from colin.compiler.state import CompilationState, OperationState
from colin.exceptions import MultipleCompilationErrors
from colin.models import (
    CalendarDuration,
    ColinConfig,
    ColinDocument,
    CompiledDocument,
    DocumentMeta,
    FileOutputMeta,
    Frontmatter,
    Manifest,
    parse_duration,
)
from colin.providers.manager import ProviderManager, create_provider_manager
from colin.providers.project import ProjectProvider
from colin.providers.storage.base import Storage
from colin.providers.variable import VariableProvider
from colin.renders import get_renderer

if TYPE_CHECKING:
    from colin.api.project import ProjectConfig


class CompileEngine:
    """Orchestrates document compilation.

    The engine performs two-pass compilation:
    1. Discovery + AST parsing to extract refs and build dependency graph
    2. Topological sort and compilation in order

    The engine handles all I/O directly:
    - Discovers models by scanning config.model_path
    - Reads source files with frontmatter parsing
    - Writes compiled outputs via artifact_storage

    ProjectProvider wraps artifact_storage for template refs.
    """

    def __init__(
        self,
        config: ProjectConfig,
        artifact_storage: Storage,
        state: CompilationState | None = None,
        force: bool = False,
        ephemeral: bool = False,
        vars: dict[str, str] | None = None,
    ) -> None:
        """Initialize the compile engine.

        Args:
            config: Project configuration with resolved paths.
            artifact_storage: Storage for compiled outputs.
            state: Optional compilation state for progress tracking.
            force: Force recompile (ignore existing manifest).
            ephemeral: Don't write to .colin/ directory (for testing, CI, one-off runs).
            vars: CLI-provided variable overrides (key=value parsed to dict).
        """
        self.config = config
        self.artifact_storage = artifact_storage
        self.state = state
        self.ephemeral = ephemeral
        self.graph = DependencyGraph()
        # Load manifest from config path (or empty if force/not exists)
        self.manifest = Manifest() if force else self._load_manifest()

        # Variable provider resolves project variables from CLI/env/defaults
        self._variable_provider = VariableProvider(
            var_configs=config.vars,
            cli_vars=vars or {},
        )

        # Project provider reads from .colin/compiled/, uses manifest for versions
        self._project_provider = ProjectProvider(
            base_path=config.build_path / "compiled",
            output_path=config.output_path,
            manifest=self.manifest,
        )

        # Compute config hash for staleness tracking and store on manifest
        self._config_hash = self._compute_config_hash()
        self.manifest.config_hash = self._config_hash
        self.manifest.project_name = config.name

    def _load_manifest(self) -> Manifest:
        """Load manifest from config path if it exists."""
        if self.config.manifest_path.exists():
            content = self.config.manifest_path.read_text(encoding="utf-8")
            return Manifest.model_validate_json(content)
        return Manifest()

    def _compute_config_hash(self) -> str:
        """Compute hash of colin.toml for staleness tracking."""
        config_path = self.config.project_root / "colin.toml"
        if config_path.exists():
            content = config_path.read_bytes()
            return hashlib.sha256(content).hexdigest()[:16]
        return ""

    def _should_publish(self, doc: ColinDocument) -> bool:
        """Check if a document should be published to output/.

        Delegates to OutputConfig.should_publish() which handles both
        explicit publish values and _ prefix naming convention.

        Args:
            doc: The document to check.

        Returns:
            True if the document should be published.
        """
        return doc.frontmatter.colin.output.should_publish(doc.uri)

    async def _is_document_stale(
        self,
        doc: ColinDocument,
        provider_manager: ProviderManager,
        recompiled_uris: set[str],
    ) -> tuple[bool, str]:
        """Check if a document needs recompilation.

        Respects the document's cache policy:
        - NEVER: Never cache, always rebuild
        - ALWAYS: Always cache, only rebuild with --no-cache
        - AUTO: Auto-invalidate on ref changes or time expiration

        Args:
            doc: The document to check.
            provider_manager: For looking up ref timestamps.
            recompiled_uris: URIs recompiled in this compilation run.

        Returns:
            Tuple of (is_stale, reason_string).
        """
        policy = doc.frontmatter.colin.cache.policy
        doc_meta = self.manifest.get_document(doc.uri)

        # Policy: never cache (always rebuild)
        if policy == "never":
            return (True, "cache=never")

        # Never compiled - rebuild regardless of policy
        if doc_meta is None or doc_meta.compiled_at is None:
            return (True, "never compiled")

        # Compiled artifact missing - rebuild (handles deleted .colin/compiled/)
        if doc_meta.output_path is not None:
            compiled_path = self.config.build_path / "compiled" / doc_meta.output_path
            if not compiled_path.exists():
                return (True, "compiled artifact missing")

        # Time-based expiration (applies to both 'always' and 'auto')
        expires_duration = doc.frontmatter.colin.cache.expires
        if expires_duration is not None:
            threshold = parse_duration(expires_duration)
            now = datetime.now(timezone.utc)

            if isinstance(threshold, CalendarDuration):
                if threshold.is_stale(doc_meta.compiled_at, now):
                    return (True, f"expired after {expires_duration}")
            else:
                if doc_meta.compiled_at + threshold < now:
                    return (True, f"expired after {expires_duration}")

        # Source changed - check before policy-specific logic
        # Both 'auto' and 'always' policies recompile on source changes
        if doc_meta.source_hash != doc.source_hash:
            return (True, "source changed")

        # Policy: always cache (ignores ref changes, only source/expiration/--no-cache)
        if policy == "always":
            return (False, "cache=always (cached)")

        # Upstream dependency recompiled this run
        for ref in doc_meta.refs:
            # Check if this ref's path matches a recompiled URI
            if ref.provider == "project":
                ref_uri = f"project://{ref.args.get('path', '')}"
                if ref_uri in recompiled_uris:
                    return (True, f"upstream recompiled: {ref_uri}")

        # Check ref versions
        stale, reason = await self._check_ref_staleness(doc_meta, provider_manager)
        if stale:
            return (True, reason)

        return (False, "up to date")

    async def _check_ref_staleness(
        self, doc_meta: DocumentMeta, provider_manager: ProviderManager
    ) -> tuple[bool, str]:
        """Check if any ref has changed version since compilation.

        Args:
            doc_meta: Document metadata with refs and ref_versions.
            provider_manager: For looking up providers.

        Returns:
            Tuple of (is_stale, reason_string).
        """
        for ref in doc_meta.refs:
            old_version = doc_meta.ref_versions.get(ref.key())
            if old_version is None:
                return (True, f"ref has no stored version: {ref.method}")

            # Handle config refs (provider config tracking)
            if ref.method == "config":
                # Get current config hash from ProjectConfig.providers
                key = f"{ref.provider}.{ref.connection}" if ref.connection else ref.provider
                inst_config = self.config.providers.get(key)
                if inst_config is None:
                    # No config entry - check if it's a built-in provider (sentinel hash)
                    from colin.providers.base import BUILTIN_CONFIG_HASH

                    if old_version == BUILTIN_CONFIG_HASH:
                        # Built-in provider with no config - still valid
                        continue
                    # Provider was removed from config
                    return (True, f"provider config removed: {ref.provider}")
                if inst_config.config_hash != old_version:
                    return (True, f"provider config changed: {ref.provider}")
                continue

            # Get provider
            if ref.provider == "project":
                provider = self._project_provider
            else:
                provider = provider_manager.get_provider(ref.provider, ref.connection or None)

            if provider is None:
                return (True, f"provider not found: {ref.provider}")

            try:
                current_version = await provider.get_ref_version(ref)
            except Exception as e:
                return (True, f"ref check failed: {ref.method} ({e})")

            if current_version != old_version:
                return (True, f"ref changed: {ref.method} ({old_version!r} -> {current_version!r})")

        return (False, "")

    async def compile_all(self) -> list[CompiledDocument]:
        """Discover and compile all documents.

        Returns:
            List of compiled documents in compilation order.
        """
        # Track cache keys used during this compilation (for pruning unused entries)
        used_cache_keys: set[str] = set()
        set_used_cache_keys(used_cache_keys)

        try:
            return await self._compile_all_inner(used_cache_keys)
        finally:
            set_used_cache_keys(None)

    async def _compile_all_inner(self, used_cache_keys: set[str]) -> list[CompiledDocument]:
        """Inner compile_all implementation."""
        # Phase 1: Discover and load documents
        documents = await self._discover_documents()

        # Prune manifest entries for removed source files
        current_uris = {doc.uri for doc in documents}
        removed_uris = set(self.manifest.documents.keys()) - current_uris
        for uri in removed_uris:
            del self.manifest.documents[uri]

        # Phase 2: Build dependency graph from refs
        self._build_dependency_graph(documents)

        # Phase 3: Topological sort
        uris = {doc.uri for doc in documents}
        compile_order = self.graph.topological_sort(uris)

        # Phase 4: Add all documents to state (if tracking)
        doc_states: dict[str, OperationState] = {}
        if self.state is not None:
            for level in compile_order:
                for uri in level:
                    doc_states[uri] = self.state.add_document(uri)

        # Phase 5: Compile levels in parallel, collecting all errors
        compiled: list[CompiledDocument] = []
        compiled_outputs: dict[str, CompiledDocument] = {}  # For in-memory ref lookup
        doc_map = {doc.uri: doc for doc in documents}
        errors: dict[str, list[Exception]] = {}
        failed_uris: set[str] = set()  # Track failed URIs for skipping dependents
        skipped_uris: set[str] = set()  # Track skipped URIs
        recompiled_uris: set[str] = set()  # Track URIs recompiled this run

        def get_failed_dependency(uri: str) -> str | None:
            """Check if any dependency of uri has failed."""
            for dep in self.graph.get_dependencies(uri):
                if dep in failed_uris:
                    return dep
            return None

        async def compile_one(
            uri: str, provider_manager: ProviderManager
        ) -> tuple[str, CompiledDocument | Exception | None, bool]:
            """Compile a single document, catching exceptions.

            Returns:
                Tuple of (uri, result, was_recompiled).
                result is None if skipped, Exception if failed.
            """
            doc_state = doc_states.get(uri)

            # Check if any upstream dependency failed
            failed_dep = get_failed_dependency(uri)
            if failed_dep:
                if doc_state:
                    doc_state.mark_skipped(f"upstream '{failed_dep}' failed")
                skipped_uris.add(uri)
                failed_uris.add(uri)  # Propagate failure to dependents
                return (uri, None, False)

            doc = doc_map[uri]

            # Check staleness
            is_stale, reason = await self._is_document_stale(doc, provider_manager, recompiled_uris)
            if not is_stale:
                # Load cached doc so downstream refs work
                cached = await self._load_cached_document(doc)
                if cached is not None:
                    if doc_state:
                        doc_state.mark_cached()
                    return (uri, cached, False)
                # Cache load failed - fall through to recompile
                # (manifest may be out of sync with storage)

            try:
                with doc_state if doc_state else _nullcontext():
                    result = await self._compile_document(
                        doc, compiled_outputs, provider_manager, doc_state
                    )
                    return (uri, result, True)
            except Exception as e:
                failed_uris.add(uri)
                return (uri, e, False)

        async with create_provider_manager(self.config) as provider_manager:
            # Register variable provider
            provider_manager.register(self._variable_provider)

            for level in compile_order:
                # Compile all documents in this level in parallel
                results = await asyncio.gather(
                    *[compile_one(uri, provider_manager) for uri in level]
                )

                # Process results
                for uri, result, was_recompiled in results:
                    if result is None:
                        # Skipped (upstream failed or cache load failed)
                        skipped_uris.add(uri)
                    elif isinstance(result, Exception):
                        errors.setdefault(uri, []).append(result)
                    elif was_recompiled:
                        # Freshly compiled - write output and update manifest
                        compiled.append(result)
                        compiled_outputs[result.output_path] = result
                        recompiled_uris.add(uri)
                        doc = doc_map[uri]
                        publish = self._should_publish(doc)
                        await self._write_output(result)
                        self._update_manifest(result, publish=publish)
                    else:
                        # Cached - just add to compiled_outputs for downstream refs
                        compiled_outputs[result.output_path] = result

        # Raise collected errors if any
        if errors:
            raise MultipleCompilationErrors(errors, skipped_uris)

        # Update manifest timestamp
        self.manifest.compiled_at = datetime.now(timezone.utc)

        # Prune unused cache entries (keeps only entries used in this run)
        unused_keys = set(self.manifest.cache.keys()) - used_cache_keys
        for key in unused_keys:
            del self.manifest.cache[key]

        # Publish public outputs to output/
        await self._publish_outputs(compiled_outputs=compiled_outputs)

        return compiled

    async def compile_uri(self, uri: str) -> CompiledDocument:
        """Compile a single document by URI.

        Writes compiled output to .colin/compiled/ but does not publish to output/.
        Use compile_all() to compile and publish all documents.

        Args:
            uri: Document URI (project:// format).

        Returns:
            The compiled document.

        Raises:
            FileNotFoundError: If the document doesn't exist.
        """
        # Convert URI to source path
        path_part = uri.replace("project://", "")
        source_file = self.config.model_path / path_part

        if not source_file.exists():
            raise FileNotFoundError(f"Model not found: {uri}")

        # Load the document
        doc = self._load_document(source_file)

        # Compile
        async with create_provider_manager(self.config) as provider_manager:
            provider_manager.register(self._variable_provider)
            result = await self._compile_document(doc, {}, provider_manager)

        # Write output and update manifest with publish status
        publish = self._should_publish(doc)
        await self._write_output(result)
        self._update_manifest(result, publish=publish)

        return result

    async def _discover_documents(self) -> list[ColinDocument]:
        """Discover and load all source models.

        Scans config.model_path for .md files, excluding nested projects.

        Returns:
            List of loaded documents.
        """
        documents: list[ColinDocument] = []

        if not self.config.model_path.exists():
            return documents

        for path in self.config.model_path.rglob("*.md"):
            # Skip files in nested projects (directories with colin.toml)
            if self._is_in_nested_project(path):
                continue

            doc = self._load_document(path)
            documents.append(doc)

        return sorted(documents, key=lambda d: d.uri)

    def _is_in_nested_project(self, path: Path) -> bool:
        """Check if path is inside a nested Colin project."""
        current = path.parent
        model_path_resolved = self.config.model_path.resolve()

        while current.resolve() != model_path_resolved:
            if (current / "colin.toml").exists():
                return True
            if current.parent == current:
                break
            current = current.parent

        return False

    def _load_document(self, path: Path) -> ColinDocument:
        """Load a source model with frontmatter.

        Args:
            path: Path to the source file.

        Returns:
            Loaded ColinDocument.
        """
        content = path.read_text(encoding="utf-8")
        post = fm_parser.loads(content)

        # Build relative path for URIs and error messages
        relative = path.relative_to(self.config.model_path)

        # Extract colin config
        raw_colin = post.metadata.pop("colin", {})
        colin_data = cast(dict[str, Any], raw_colin) if isinstance(raw_colin, dict) else {}
        try:
            colin_config = ColinConfig.model_validate(colin_data)
        except Exception as e:
            raise ValueError(f"Invalid frontmatter in {relative}:\n{e}") from e

        # Rest is document metadata
        metadata = cast(dict[str, Any], post.metadata)
        frontmatter = Frontmatter(colin=colin_config, metadata=metadata)
        uri = f"project://{relative}"

        # Hash the FULL content (including frontmatter) for change detection
        # This ensures changes to colin.output, colin.private, etc. invalidate cache
        source_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

        return ColinDocument(
            uri=uri,
            frontmatter=frontmatter,
            template_content=post.content,
            source_hash=source_hash,
        )

    def _build_dependency_graph(self, documents: list[ColinDocument]) -> None:
        """Build dependency graph from static refs and explicit depends_on hints.

        Sources of dependencies:
        1. Static refs extracted from Jinja AST (ref('literal.md') calls)
        2. Explicit depends_on hints from frontmatter

        Note: Empirical refs from manifest are NOT used for ordering - they are
        only used for staleness detection. This ensures consistent behavior
        regardless of manifest state.

        Args:
            documents: List of documents to analyze.
        """
        # Build output_path → source_uri mapping for resolving refs like ref("config.json")
        # when the source is config.md with colin.output: json
        output_path_to_uri: dict[str, str] = {}
        for doc in documents:
            output_path = self._compute_output_path(doc)
            output_path_to_uri[output_path] = doc.uri

        # Use full environment with extensions so {% llm %} etc. are recognized
        env = create_jinja_environment()

        for doc in documents:
            # 1. Extract static refs from AST
            try:
                ast = env.parse(doc.template_content)
                refs = self._extract_refs_from_ast(ast)
                for ref_uri in refs:
                    # Normalize ref URIs to match document URIs (project://...)
                    normalized_ref = self._normalize_uri(ref_uri, output_path_to_uri)
                    self.graph.add_edge(doc.uri, normalized_ref)
            except TemplateSyntaxError:
                # If parsing fails, we'll catch actual errors during compilation
                pass

            # 2. Add explicit depends_on hints from frontmatter
            for dep in doc.frontmatter.colin.depends_on:
                # Resolve dependency path to URI
                normalized_dep = self._normalize_uri(dep, output_path_to_uri)
                self.graph.add_edge(doc.uri, normalized_dep)

    def _compute_output_path(self, doc: ColinDocument) -> str:
        """Compute the output path for a document based on its output config.

        Uses explicit output.path if set, otherwise derives from source filename
        with the renderer's extension.

        Args:
            doc: The document to compute output path for.

        Returns:
            The output filename (e.g., 'config.json' for json output).
        """
        output_config = doc.frontmatter.colin.output
        renderer = get_renderer(output_config.format)
        # Extract path from URI (project://path.md -> path.md)
        uri_path = doc.uri.split("://", 1)[1] if "://" in doc.uri else doc.uri
        return renderer._get_output_filename(uri_path, output_config)

    def _normalize_uri(
        self, ref_target: str, output_path_to_uri: dict[str, str] | None = None
    ) -> str:
        """Resolve a ref target to a source document URI.

        Refs must specify exact output filename (no magic .md suffix).
        Uses output_path_to_uri mapping to resolve output filenames to source URIs.

        Args:
            ref_target: What the user wrote in ref(), e.g., "config.json" or "project://foo".
            output_path_to_uri: Mapping from output_path to source URI.

        Returns:
            Source document URI for dependency tracking.
        """
        # Already has a scheme - leave as-is
        if "://" in ref_target:
            return ref_target

        # Look up output_path → source URI
        if output_path_to_uri is not None and ref_target in output_path_to_uri:
            return output_path_to_uri[ref_target]

        # Not found - construct URI anyway (will fail at compile time)
        return f"project://{ref_target}"

    def _extract_refs_from_ast(self, ast: nodes.Template) -> list[str]:
        """Extract ref() URIs from Jinja AST.

        Refs with allow_stale=True are excluded since they don't create
        ordering dependencies (used to break cycles).

        Args:
            ast: Parsed Jinja template AST.

        Returns:
            List of ref URIs found in the template (excluding allow_stale refs).
        """
        refs: list[str] = []

        def visit(node: nodes.Node) -> None:
            if isinstance(node, nodes.Call):
                # Check for ref('uri') pattern
                if isinstance(node.node, nodes.Name) and node.node.name == "ref":
                    # Check for allow_stale=True - if set, don't add ordering edge
                    has_allow_stale = any(
                        kw.key == "allow_stale"
                        and isinstance(kw.value, nodes.Const)
                        and kw.value.value is True
                        for kw in node.kwargs
                    )
                    if not has_allow_stale:
                        if node.args and isinstance(node.args[0], nodes.Const):
                            ref_uri = node.args[0].value
                            if isinstance(ref_uri, str):
                                refs.append(ref_uri)

            # Recurse into child nodes
            for child in node.iter_child_nodes():
                visit(child)

        visit(ast)
        return refs

    async def _compile_document(
        self,
        doc: ColinDocument,
        compiled_outputs: dict[str, CompiledDocument],
        provider_manager: ProviderManager,
        doc_state: OperationState | None = None,
    ) -> CompiledDocument:
        """Compile a single document.

        Args:
            doc: The document to compile.
            compiled_outputs: Already-compiled documents from this run.
            provider_manager: Provider manager for external resource access.
            doc_state: Optional state for progress tracking.

        Returns:
            The compiled document.
        """
        # Check if template processing is disabled
        if not doc.frontmatter.colin.template:
            # Skip Jinja entirely - just use content as-is
            output_config = doc.frontmatter.colin.output
            renderer = get_renderer(output_config.format)
            render_result = renderer.render(doc.template_content, doc.uri, output_config)
            output_hash = hashlib.sha256(render_result.content.encode()).hexdigest()[:16]

            return CompiledDocument(
                uri=doc.uri,
                frontmatter=doc.frontmatter,
                output=render_result.content,
                output_path=render_result.filename,
                source_hash=doc.source_hash,
                output_hash=output_hash,
                file_outputs={},
                file_output_meta={},
                sections={},
                llm_calls={},
                refs=[],
                total_cost_usd=0.0,
            )

        # Create Jinja environment with extensions
        env = create_jinja_environment()

        # Create compile context
        context = CompileContext(
            manifest=self.manifest,
            document_uri=doc.uri,
            project_provider=self._project_provider,
            config=self.config,
            output_format=doc.frontmatter.colin.output.format,
            compiled_outputs=compiled_outputs,
            doc_state=doc_state,
        )

        # Bind context to environment
        bind_context_to_environment(
            env,
            context,
            provider_manager=provider_manager,
        )

        # Compile template with compile context set for caching
        template = env.from_string(doc.template_content)

        set_compile_context(context)
        try:
            # FIRST PASS: Render template (defer blocks emit markers)
            context.defer_blocks = {}  # Initialize defer block storage
            raw_output = await template.render_async()

            # Extract sections from first pass
            from colin.compiler.section_parser import (
                parse_sections,
                remove_section_and_defer_markers,
            )

            first_pass_sections = parse_sections(raw_output)
            context.sections = first_pass_sections

            # TWO-PASS RENDERING: If defer blocks exist, do second pass
            if context.defer_blocks:
                # Create RenderedOutput for current render (first pass)
                from colin.compiler.rendered import RenderedOutput

                rendered = RenderedOutput(
                    content=raw_output,
                    sections=first_pass_sections,
                    output_format=doc.frontmatter.colin.output.format,
                )

                # SECOND PASS: Render defer blocks with rendered context
                # Note: Use output(cached=True) in templates to access previous output
                defer_outputs = {}
                for defer_id, caller in context.defer_blocks.items():
                    defer_content = await caller(rendered)
                    defer_outputs[defer_id] = defer_content

                # Merge defer block outputs into first pass output
                final_output = self._merge_defer_blocks(raw_output, defer_outputs)

                # Re-extract sections (defer blocks might have added sections)
                context.sections = parse_sections(final_output)
            else:
                final_output = raw_output

            # Remove section and defer markers, but keep item markers for the renderer
            # The markdown parser needs item markers to detect {% item %} arrays
            clean_output = remove_section_and_defer_markers(final_output)

            # Apply format renderer (JSON, YAML, or markdown passthrough)
            output_config = doc.frontmatter.colin.output
            renderer = get_renderer(output_config.format)
            render_result = renderer.render(clean_output, doc.uri, output_config)
        finally:
            set_compile_context(None)

        # Hash the FINAL rendered content
        output_hash = hashlib.sha256(render_result.content.encode()).hexdigest()[:16]

        # Convert file outputs from context to compiled document format
        file_outputs: dict[str, str] = {}
        file_output_meta: dict[str, FileOutputMeta] = {}
        for path, file_output in context.file_outputs.items():
            file_outputs[path] = file_output.content
            file_output_meta[path] = FileOutputMeta(
                publish=file_output.publish,
                format=file_output.format,
                sections=file_output.sections,
                output_hash=file_output.output_hash,
            )

        return CompiledDocument(
            uri=doc.uri,
            frontmatter=doc.frontmatter,
            output=render_result.content,
            output_path=render_result.filename,
            source_hash=doc.source_hash,
            output_hash=output_hash,
            refs=context.refs,
            ref_versions=context.ref_versions,
            llm_calls=context.llm_calls,
            total_cost_usd=context.total_cost,
            sections=context.sections,
            file_outputs=file_outputs,
            file_output_meta=file_output_meta,
        )

    async def _load_cached_document(self, doc: ColinDocument) -> CompiledDocument | None:
        """Load a cached document from storage.

        When a document is not stale, we need to load its compiled output
        so downstream documents can ref() it.

        Args:
            doc: The source document (for frontmatter).

        Returns:
            The cached CompiledDocument, or None if not found in manifest/storage.
        """
        meta = self.manifest.get_document(doc.uri)
        if meta is None or meta.output_path is None:
            return None

        try:
            content = await self.artifact_storage.read(meta.output_path)
        except FileNotFoundError:
            return None

        # Use manifest hash if available, otherwise compute from content
        output_hash = meta.output_hash
        if not output_hash:
            output_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

        return CompiledDocument(
            uri=doc.uri,
            frontmatter=doc.frontmatter,
            output=content,
            source_hash=doc.source_hash,
            output_hash=output_hash,
            output_path=meta.output_path,
            refs=meta.refs,
            ref_versions=meta.ref_versions,
            llm_calls=meta.llm_calls,
            total_cost_usd=meta.total_cost_usd,
            sections=meta.sections,
        )

    async def _write_output(self, doc: CompiledDocument) -> None:
        """Write pre-rendered output to storage with content-addressing.

        Content is already rendered during compilation. Only writes if
        the output hash differs from existing file or artifact is missing.
        Skips writing in ephemeral mode.

        Args:
            doc: The compiled document (must have output_path and output set).
        """
        # Skip writes in ephemeral mode
        if self.ephemeral:
            return

        # Content-addressed: only write if hash differs or artifact missing
        existing_meta = self.manifest.get_document(doc.uri)
        artifact_path = self.config.build_path / "compiled" / doc.output_path
        if (
            existing_meta is None
            or existing_meta.output_hash != doc.output_hash
            or not artifact_path.exists()
        ):
            await self.artifact_storage.write(doc.output_path, doc.output)

        # Write file outputs from {% file %} blocks
        for path, content in doc.file_outputs.items():
            file_artifact_path = self.config.build_path / "compiled" / path
            # Always write file outputs (they're dynamic, can't easily content-address)
            if not file_artifact_path.exists() or file_artifact_path.read_text() != content:
                await self.artifact_storage.write(path, content)

    def _merge_defer_blocks(self, output: str, defer_outputs: dict[str, str]) -> str:
        """Replace defer markers with rendered defer block content.

        Args:
            output: First pass output with defer markers.
            defer_outputs: Map of defer_id to rendered defer content.

        Returns:
            Output with defer markers replaced by rendered content.
        """
        from colin.compiler.extensions.defer_block import (
            DEFER_END_MARKER,
            DEFER_START_MARKER,
        )

        result = output
        for defer_id, defer_content in defer_outputs.items():
            marker_start = DEFER_START_MARKER.format(id=defer_id)
            marker_end = DEFER_END_MARKER.format(id=defer_id)
            pattern = f"{marker_start}{marker_end}"
            result = result.replace(pattern, defer_content)
        return result

    def _update_manifest(self, doc: CompiledDocument, *, publish: bool) -> None:
        """Update manifest with compilation result.

        Args:
            doc: The compiled document.
            publish: Whether this document should be published to output/.
        """
        meta = DocumentMeta(
            uri=doc.uri,
            source_hash=doc.source_hash,
            output_hash=doc.output_hash,
            output_path=doc.output_path,
            is_published=publish,
            compiled_at=datetime.now(timezone.utc),
            refs=doc.refs,
            ref_versions=doc.ref_versions,
            llm_calls=doc.llm_calls,
            total_cost_usd=doc.total_cost_usd,
            sections=doc.sections,
            file_outputs=doc.file_output_meta,
            config_hash=self._config_hash,
        )
        self.manifest.set_document(doc.uri, meta)

    async def _publish_outputs(
        self,
        *,
        compiled_outputs: dict[str, CompiledDocument] | None = None,
    ) -> None:
        """Publish public outputs from .colin/compiled/ to output/.

        Uses manifest metadata to copy files without re-rendering.
        Prefers in-memory compiled_outputs (freshly compiled this run) over
        cached files on disk to ensure ephemeral mode publishes fresh content.

        Note: This method only writes/overwrites files, never deletes. Use
        `colin clean` to remove output directory before a fresh build.

        Args:
            compiled_outputs: In-memory compiled docs, preferred over disk cache.
        """
        output_path = self.config.output_path

        # Create output directory (never delete - use `colin clean` for that)
        output_path.mkdir(parents=True, exist_ok=True)

        # Copy public files from .colin/compiled/ to output/
        build_compiled = self.config.build_path / "compiled"
        for doc_meta in self.manifest.documents.values():
            # Publish main output if document is published
            if doc_meta.is_published and doc_meta.output_path is not None:
                src = build_compiled / doc_meta.output_path
                dst = output_path / doc_meta.output_path
                dst.parent.mkdir(parents=True, exist_ok=True)

                if compiled_outputs and doc_meta.output_path in compiled_outputs:
                    # Prefer in-memory compiled output (freshly compiled this run)
                    dst.write_text(compiled_outputs[doc_meta.output_path].output, encoding="utf-8")
                elif src.exists():
                    shutil.copy2(src, dst)

            # Publish file outputs from {% file %} blocks
            # (even if main doc is private, file outputs can be explicitly published)
            for file_path, file_meta in doc_meta.file_outputs.items():
                # Determine publish status: explicit > inherit from source doc
                should_publish = (
                    file_meta.publish if file_meta.publish is not None else doc_meta.is_published
                )
                if not should_publish:
                    continue

                file_src = build_compiled / file_path
                file_dst = output_path / file_path
                file_dst.parent.mkdir(parents=True, exist_ok=True)

                # Prefer in-memory content if available
                if compiled_outputs and doc_meta.output_path in compiled_outputs:
                    compiled_doc = compiled_outputs[doc_meta.output_path]
                    if file_path in compiled_doc.file_outputs:
                        file_dst.write_text(compiled_doc.file_outputs[file_path], encoding="utf-8")
                        continue
                if file_src.exists():
                    shutil.copy2(file_src, file_dst)

        # Write output manifests for ownership tracking
        await self._write_output_manifests(compiled_outputs=compiled_outputs)

    async def _write_output_manifests(
        self,
        *,
        compiled_outputs: dict[str, CompiledDocument] | None = None,
    ) -> None:
        """Write .colin-manifest.json files for ownership tracking.

        Each manifest claims ownership of its directory, enabling safe cleanup
        of stale files without touching user-created content.

        Args:
            compiled_outputs: In-memory compiled docs for content hashing.
        """
        # Skip in ephemeral mode
        if self.ephemeral:
            return

        project_file = self.config.project_root / "colin.toml"

        # Collect all published file paths with their content hashes
        published_files: dict[str, str] = {}  # path -> hash
        for doc_meta in self.manifest.documents.values():
            if doc_meta.is_published and doc_meta.output_path:
                # Get hash from in-memory if available, else from manifest
                if compiled_outputs and doc_meta.output_path in compiled_outputs:
                    content_hash = compiled_outputs[doc_meta.output_path].output_hash
                else:
                    content_hash = doc_meta.output_hash or ""
                published_files[doc_meta.output_path] = content_hash

            # Include file outputs
            for file_path, file_meta in doc_meta.file_outputs.items():
                should_publish = (
                    file_meta.publish if file_meta.publish is not None else doc_meta.is_published
                )
                if should_publish:
                    published_files[file_path] = file_meta.output_hash or ""

        if not published_files:
            return

        # Get manifest locations from output target
        from colin.api.project import create_output_target

        target_kwargs: dict[str, Any] = {}
        # Use explicit output.path if set, otherwise fall back to resolved output_path
        if self.config.output.path:
            target_kwargs["path"] = self.config.output.path
        else:
            target_kwargs["path"] = str(self.config.output_path)
        if self.config.output.scope:
            target_kwargs["scope"] = self.config.output.scope
        if self.config.output.model_extra:
            for key, value in self.config.output.model_extra.items():
                target_kwargs[key] = value

        target = create_output_target(self.config.output.target, **target_kwargs)
        locations = target.get_manifest_locations(list(published_files.keys()))

        output_path = self.config.output_path

        # Write manifest for each location
        for location in locations:
            # Filter files for this location
            prefix = f"{location}/" if location else ""
            location_files: dict[str, str] = {}

            for path, content_hash in published_files.items():
                if location:
                    # File must be under this subdir
                    if path.startswith(prefix):
                        rel_path = path[len(prefix) :]
                        location_files[rel_path] = content_hash
                else:
                    # Root manifest - include files not in any subdir
                    # (or all files if this is the only location)
                    if len(locations) == 1 or "/" not in path:
                        location_files[path] = content_hash

            if not location_files:
                continue

            # Write manifest
            manifest_dir = output_path / location if location else output_path
            manifest_path = manifest_dir / ".colin-manifest.json"
            manifest_data = {
                "project_name": self.config.name,
                "project_config": str(project_file),
                "output_root": str(output_path),
                "vars": self._variable_provider.cli_vars,
                "files": location_files,
            }
            manifest_path.write_text(
                json.dumps(manifest_data, indent=2, sort_keys=True), encoding="utf-8"
            )
