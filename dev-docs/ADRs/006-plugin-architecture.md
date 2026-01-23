# ADR 006: Plugin Architecture from Day One

**Status**: Accepted
**Date**: 2024-12-27

## Context

Colin needs to support multiple input sources (files, MCP, remote Colin), output formats (markdown, skills, RAG), and materialization strategies (DAG, BFS). These are natural extension points.

## Decision

Define plugin protocols from day one, even though MVP only uses default implementations:

### InputPlugin
```python
class InputPlugin(Protocol):
    scheme: str  # "file", "mcp", "colin"
    async def fetch(self, uri: str) -> RefResult: ...
    async def hash(self, uri: str) -> str: ...
```

### OutputPlugin
```python
class OutputPlugin(Protocol):
    name: str  # "markdown", "skill", "rag"
    async def emit(self, doc: CompiledDocument, output_dir: Path) -> list[Path]: ...
```

### MaterializationPlugin
```python
class MaterializationPlugin(Protocol):
    name: str  # "dag", "bfs", "streaming"
    async def materialize(
        self,
        changed: set[str],
        graph: DependencyGraph,
        compile_fn: Callable[[str], Awaitable[CompiledDocument]],
    ) -> list[str]: ...
```

### MVP Defaults
- Input: `file` (local `.colin` files)
- Output: `markdown` (raw markdown to `dist/`)
- Materialization: `dag` (topological sort, fails on cycles)

## Rationale

1. **Clean interfaces**: Protocols define the contract before implementation
2. **Testable**: Can swap stub implementations for testing
3. **Future-proof**: Adding MCP or Skills is just a new plugin
4. **Type safe**: Protocol-based for static type checking

## Consequences

- Slightly more code upfront (protocols + implementations)
- Engine is decoupled from specific implementations
- Clear extension points for future features
