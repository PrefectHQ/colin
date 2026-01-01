"""Colin compilation engine."""

from __future__ import annotations

import asyncio
import hashlib
from contextlib import nullcontext as _nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import frontmatter as fm_parser
from jinja2 import TemplateSyntaxError, nodes

from colin.compiler.context import CompileContext
from colin.compiler.graph import DependencyGraph
from colin.compiler.jinja_env import bind_context_to_environment, create_jinja_environment
from colin.compiler.state import CompilationState, OperationState
from colin.exceptions import MultipleCompilationErrors
from colin.models import (
    Address,
    CalendarDuration,
    ColinConfig,
    ColinDocument,
    CompiledDocument,
    DocumentMeta,
    Frontmatter,
    Manifest,
    RefreshPolicy,
    parse_duration,
)
from colin.providers.cache import set_compile_context
from colin.providers.manager import ProviderManager, create_provider_manager
from colin.providers.project import ProjectProvider
from colin.providers.storage.base import Storage
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
    ) -> None:
        """Initialize the compile engine.

        Args:
            config: Project configuration with resolved paths.
            artifact_storage: Storage for compiled outputs.
            state: Optional compilation state for progress tracking.
            force: Force recompile (ignore existing manifest).
        """
        self.config = config
        self.artifact_storage = artifact_storage
        self.state = state
        self.graph = DependencyGraph()
        # Load manifest from config path (or empty if force/not exists)
        self.manifest = Manifest() if force else self._load_manifest()

        # Project provider reads from target directory, uses manifest for timestamps
        self._project_provider = ProjectProvider(
            base_path=config.target_path, manifest=self.manifest
        )

    def _load_manifest(self) -> Manifest:
        """Load manifest from config path if it exists."""
        if self.config.manifest_path.exists():
            content = self.config.manifest_path.read_text(encoding="utf-8")
            return Manifest.model_validate_json(content)
        return Manifest()

    async def _is_document_stale(
        self,
        doc: ColinDocument,
        provider_manager: ProviderManager,
        recompiled_uris: set[str],
    ) -> tuple[bool, str]:
        """Check if a document needs recompilation.

        Respects the document's refresh policy:
        - ALWAYS: Always rebuild
        - ONCE: Only build if no cached output exists
        - AUTO: Rebuild if stale (source changed, refs updated, time expired)

        Args:
            doc: The document to check.
            provider_manager: For looking up ref timestamps.
            recompiled_uris: URIs recompiled in this compilation run.

        Returns:
            Tuple of (is_stale, reason_string).
        """
        policy = doc.frontmatter.colin.refresh.policy
        doc_meta = self.manifest.get_document(doc.uri)

        # Policy: always rebuild
        if policy == RefreshPolicy.ALWAYS:
            return (True, "refresh=always")

        # Policy: once (only build if no cache)
        if policy == RefreshPolicy.ONCE:
            if doc_meta is None or doc_meta.compiled_at is None:
                return (True, "no cached output")
            # Check if output file exists
            return (False, "refresh=once (cached)")

        # Policy: auto - check staleness conditions
        # Never compiled
        if doc_meta is None or doc_meta.compiled_at is None:
            return (True, "never compiled")

        # Source changed
        if doc_meta.source_hash != doc.source_hash:
            return (True, "source changed")

        # Time-based expiration
        stale_duration = doc.frontmatter.colin.refresh.stale
        if stale_duration is not None:
            threshold = parse_duration(stale_duration)
            now = datetime.now(timezone.utc)

            if isinstance(threshold, CalendarDuration):
                # Calendar-aligned: check if enough calendar periods have passed
                if threshold.is_stale(doc_meta.compiled_at, now):
                    return (True, f"stale after {stale_duration}")
            else:
                # Elapsed duration (timedelta or relativedelta)
                # For relativedelta, we add it to compiled_at and compare
                if doc_meta.compiled_at + threshold < now:
                    return (True, f"stale after {stale_duration}")

        # Upstream dependency recompiled this run
        for ref_addr in doc_meta.refs_evaluated:
            # Check if this ref's path matches a recompiled URI
            if ref_addr["provider"] == "project":
                ref_uri = f"project://{ref_addr['payload'].get('path', '')}"
                if ref_uri in recompiled_uris:
                    return (True, f"upstream recompiled: {ref_uri}")

        # Check ref timestamps
        for ref_addr in doc_meta.refs_evaluated:
            ref_updated = await self._get_ref_last_updated(ref_addr, provider_manager)
            ref_display = f"{ref_addr['provider']}://{ref_addr['payload']}"
            if ref_updated is None:
                return (True, f"ref timestamp unknown: {ref_display}")
            if ref_updated > doc_meta.compiled_at:
                return (True, f"ref updated: {ref_display}")

        return (False, "up to date")

    async def _get_ref_last_updated(
        self, addr: Address, provider_manager: ProviderManager
    ) -> datetime | None:
        """Get last update time for a referenced address.

        Routes to appropriate provider based on address.

        Args:
            addr: Structured address with provider, instance, payload.
            provider_manager: For external provider lookups.

        Returns:
            Last update time, or None if unknown.
        """
        provider_name = addr["provider"]
        instance = addr["instance"]
        payload = addr["payload"]

        # Project refs use our project provider (which has manifest)
        if provider_name == "project":
            return await self._project_provider.get_last_updated(payload)

        # Other providers go through provider manager
        provider = provider_manager.get_provider(provider_name, instance or None)
        if provider is None:
            return None
        return await provider.get_last_updated(payload)

    async def compile_all(self) -> list[CompiledDocument]:
        """Discover and compile all documents.

        Returns:
            List of compiled documents in compilation order.
        """
        # Phase 1: Discover and load documents
        documents = await self._discover_documents()

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
                if doc_state:
                    doc_state.mark_cached()
                skipped_uris.add(uri)
                return (uri, None, False)

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
            for level in compile_order:
                # Compile all documents in this level in parallel
                results = await asyncio.gather(
                    *[compile_one(uri, provider_manager) for uri in level]
                )

                # Process results
                for uri, result, was_recompiled in results:
                    if result is None:
                        # Skipped - already handled above
                        pass
                    elif isinstance(result, Exception):
                        errors.setdefault(uri, []).append(result)
                    else:
                        compiled.append(result)
                        compiled_outputs[uri] = result
                        if was_recompiled:
                            recompiled_uris.add(uri)
                        await self._write_output(result)
                        self._update_manifest(result)

        # Raise collected errors if any
        if errors:
            raise MultipleCompilationErrors(errors, skipped_uris)

        # Update manifest timestamp
        self.manifest.compiled_at = datetime.now(timezone.utc)

        return compiled

    async def compile_uri(self, uri: str) -> CompiledDocument:
        """Compile a single document by URI.

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
            result = await self._compile_document(doc, {}, provider_manager)

        # Write output
        await self._write_output(result)

        # Update manifest
        self._update_manifest(result)

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

        # Extract colin config
        raw_colin = post.metadata.pop("colin", {})
        colin_data = cast(dict[str, Any], raw_colin) if isinstance(raw_colin, dict) else {}
        colin_config = ColinConfig.model_validate(colin_data)

        # Rest is document metadata
        metadata = cast(dict[str, Any], post.metadata)
        frontmatter = Frontmatter(colin=colin_config, metadata=metadata)

        # Build URI from path
        relative = path.relative_to(self.config.model_path)
        uri = f"project://{relative}"

        # Hash the template content for change detection
        source_hash = hashlib.sha256(post.content.encode()).hexdigest()[:16]

        return ColinDocument(
            uri=uri,
            frontmatter=frontmatter,
            template_content=post.content,
            source_hash=source_hash,
        )

    def _build_dependency_graph(self, documents: list[ColinDocument]) -> None:
        """Build dependency graph by parsing refs from templates.

        Uses Jinja AST to extract ref() calls without executing templates.

        Args:
            documents: List of documents to analyze.
        """
        # Use full environment with extensions so {% llm %} etc. are recognized
        env = create_jinja_environment()

        for doc in documents:
            try:
                ast = env.parse(doc.template_content)
                refs = self._extract_refs_from_ast(ast)
                for ref_uri in refs:
                    # Normalize ref URIs to match document URIs (project://...)
                    normalized_ref = self._normalize_uri(ref_uri)
                    self.graph.add_edge(doc.uri, normalized_ref)
            except TemplateSyntaxError:
                # If parsing fails, we'll catch actual errors during compilation
                pass

    def _normalize_uri(self, uri: str) -> str:
        """Normalize a URI to project:// format.

        Converts shorthand refs like 'data' to 'project://data.md'.

        Args:
            uri: URI in any format (shorthand or full).

        Returns:
            Normalized URI.
        """
        # Already has a scheme - leave as-is
        if "://" in uri:
            return uri

        # Schemaless shorthand - normalize to project://
        # Add .md extension if missing
        if not uri.endswith(".md"):
            uri = f"{uri}.md"
        return f"project://{uri}"

    def _extract_refs_from_ast(self, ast: nodes.Template) -> list[str]:
        """Extract ref() URIs from Jinja AST.

        Args:
            ast: Parsed Jinja template AST.

        Returns:
            List of ref URIs found in the template.
        """
        refs: list[str] = []

        def visit(node: nodes.Node) -> None:
            if isinstance(node, nodes.Call):
                # Check for ref('uri') pattern
                if isinstance(node.node, nodes.Name) and node.node.name == "ref":
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
        provider_manager,
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
        # Create Jinja environment with extensions
        env = create_jinja_environment()

        # Create compile context
        context = CompileContext(
            manifest=self.manifest,
            document_uri=doc.uri,
            project_provider=self._project_provider,
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
            output = await template.render_async()
        finally:
            set_compile_context(None)

        # Calculate output hash
        output_hash = hashlib.sha256(output.encode()).hexdigest()[:16]

        return CompiledDocument(
            uri=doc.uri,
            frontmatter=doc.frontmatter,
            output=output,
            source_hash=doc.source_hash,
            output_hash=output_hash,
            refs_evaluated=context.refs_evaluated,
            llm_calls=context.llm_calls,
            total_cost_usd=context.total_cost,
        )

    async def _write_output(self, doc: CompiledDocument) -> None:
        """Write compiled output to storage.

        Uses the renderer specified in frontmatter.colin.output (default: markdown).

        Args:
            doc: The compiled document.
        """
        # Get renderer from frontmatter
        output_format = doc.frontmatter.colin.output
        renderer = get_renderer(output_format)

        # Render the document
        render_result = renderer.render(doc)

        # Write to artifact storage (relative path)
        await self.artifact_storage.write(render_result.filename, render_result.content)

    def _update_manifest(self, doc: CompiledDocument) -> None:
        """Update manifest with compilation result.

        Args:
            doc: The compiled document.
        """
        meta = DocumentMeta(
            uri=doc.uri,
            source_hash=doc.source_hash,
            output_hash=doc.output_hash,
            compiled_at=datetime.now(timezone.utc),
            refs_evaluated=doc.refs_evaluated,
            llm_calls=doc.llm_calls,
            total_cost_usd=doc.total_cost_usd,
        )
        self.manifest.set_document(doc.uri, meta)
