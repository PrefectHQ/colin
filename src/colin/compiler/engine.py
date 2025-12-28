"""Colin compilation engine."""

from __future__ import annotations

import asyncio
import hashlib
from contextlib import nullcontext as _nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from fastmcp.mcp_config import MCPConfig
from jinja2 import nodes

from colin.compiler.context import CompileContext
from colin.compiler.graph import DependencyGraph
from colin.compiler.jinja_env import bind_context_to_environment, create_jinja_environment
from colin.compiler.state import CompilationState, OperationState
from colin.exceptions import MultipleCompilationErrors
from colin.mcp import MCPManager
from colin.models import (
    ColinDocument,
    CompiledDocument,
    DocumentMeta,
    Manifest,
)

if TYPE_CHECKING:
    from colin.plugins.inputs.file import FileInputPlugin


class CompileEngine:
    """Orchestrates document compilation.

    The engine performs two-pass compilation:
    1. Discovery + AST parsing to extract refs and build dependency graph
    2. Topological sort and compilation in order
    """

    def __init__(
        self,
        manifest: Manifest,
        input_plugin: FileInputPlugin,
        default_model: str,
        mcp_config: MCPConfig | None = None,
        state: CompilationState | None = None,
    ) -> None:
        """Initialize the compile engine.

        Args:
            manifest: The manifest for caching and metadata.
            input_plugin: Input plugin for document access.
            default_model: Default LLM model to use.
            mcp_config: MCP server configuration.
            state: Optional compilation state for progress tracking.
        """
        self.manifest = manifest
        self.input_plugin = input_plugin
        self.default_model = default_model
        self.mcp_config = mcp_config or MCPConfig()
        self.state = state
        self.graph = DependencyGraph()

    async def compile_all(self) -> list[CompiledDocument]:
        """Discover and compile all documents.

        Returns:
            List of compiled documents in compilation order.
        """
        # Phase 1: Discover and load documents
        documents = self._discover_documents()

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

        async def compile_one(uri: str) -> tuple[str, CompiledDocument | Exception]:
            """Compile a single document, catching exceptions."""
            doc = doc_map[uri]
            doc_state = doc_states.get(uri)
            try:
                with doc_state if doc_state else _nullcontext():
                    result = await self._compile_document(
                        doc, compiled_outputs, mcp_manager, doc_state
                    )
                    return (uri, result)
            except Exception as e:
                return (uri, e)

        # Create MCP manager for resource access
        mcp_manager = MCPManager(self.mcp_config)
        try:
            for level in compile_order:
                # Compile all documents in this level in parallel
                results = await asyncio.gather(*[compile_one(uri) for uri in level])

                # Process results
                for uri, result in results:
                    if isinstance(result, Exception):
                        errors.setdefault(uri, []).append(result)
                    else:
                        compiled.append(result)
                        compiled_outputs[uri] = result
                        self._write_output(result)
                        self._update_manifest(result)
        finally:
            await mcp_manager.close()

        # Raise collected errors if any
        if errors:
            raise MultipleCompilationErrors(errors)

        # Update manifest timestamp
        self.manifest.compiled_at = datetime.now(timezone.utc)

        return compiled

    async def compile_uri(self, uri: str) -> CompiledDocument:
        """Compile a single document by URI.

        Args:
            uri: Document URI to compile.

        Returns:
            The compiled document.

        Raises:
            FileNotFoundError: If the document doesn't exist.
        """
        # Load the document
        model_path = self.input_plugin.uri_to_model_path(uri)
        if model_path is None:
            raise FileNotFoundError(f"Document not found: {uri}")

        doc = self._load_document(uri, model_path)

        # Compile
        result = await self._compile_document(doc, {})

        # Write output
        self._write_output(result)

        # Update manifest
        self._update_manifest(result)

        return result

    def _discover_documents(self) -> list[ColinDocument]:
        """Discover and load all documents.

        Returns:
            List of loaded documents.
        """
        documents: list[ColinDocument] = []
        for uri, path in self.input_plugin.discover_documents():
            doc = self._load_document(uri, path)
            documents.append(doc)
        return documents

    def _load_document(self, uri: str, path: Path) -> ColinDocument:
        """Load a single document from disk.

        Args:
            uri: Document URI.
            path: Path to the source file.

        Returns:
            Loaded ColinDocument.
        """
        frontmatter, template_content = self.input_plugin.parse_frontmatter(path)
        content = path.read_text(encoding="utf-8")
        source_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

        return ColinDocument(
            uri=uri,
            source_path=path,
            frontmatter=frontmatter,
            template_content=template_content,
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
                    normalized_ref = self.input_plugin.normalize_uri(ref_uri)
                    self.graph.add_edge(doc.uri, normalized_ref)
            except Exception:
                # If parsing fails, we'll catch actual errors during compilation
                pass

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
        mcp_manager: MCPManager | None = None,
        doc_state: OperationState | None = None,
    ) -> CompiledDocument:
        """Compile a single document.

        Args:
            doc: The document to compile.
            compiled_outputs: Already-compiled documents from this run.
            mcp_manager: MCP manager for resource access.
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
            default_model=self.default_model,
            input_plugin=self.input_plugin,
            compiled_outputs=compiled_outputs,
            mcp_manager=mcp_manager,
            doc_state=doc_state,
        )

        # Bind context to environment
        bind_context_to_environment(env, context)

        # Compile template
        template = env.from_string(doc.template_content)
        output = await template.render_async()

        # Calculate output hash
        output_hash = hashlib.sha256(output.encode()).hexdigest()[:16]

        return CompiledDocument(
            uri=doc.uri,
            source_path=doc.source_path,
            frontmatter=doc.frontmatter,
            output=output,
            source_hash=doc.source_hash,
            output_hash=output_hash,
            refs_evaluated=context.refs_evaluated,
            llm_calls=context.llm_calls,
            total_cost_usd=context.total_cost,
        )

    def _write_output(self, doc: CompiledDocument) -> None:
        """Write compiled output to disk.

        Args:
            doc: The compiled document.
        """
        target_path = self.input_plugin.uri_to_target_path(doc.uri)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(doc.output, encoding="utf-8")

    def _update_manifest(self, doc: CompiledDocument) -> None:
        """Update manifest with compilation result.

        Args:
            doc: The compiled document.
        """
        meta = DocumentMeta(
            uri=doc.uri,
            source_path=str(doc.source_path),
            source_hash=doc.source_hash,
            output_hash=doc.output_hash,
            compiled_at=datetime.now(timezone.utc),
            refs_evaluated=doc.refs_evaluated,
            llm_calls=doc.llm_calls,
            total_cost_usd=doc.total_cost_usd,
        )
        self.manifest.set_document(doc.uri, meta)
