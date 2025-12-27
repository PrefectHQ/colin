# Colin Development Guidelines

Colin (**Co**ntext **Lin**eage) is a context compiler for the AI era. It takes interconnected source documents, resolves dependencies, applies transformations (including LLM calls), and compiles them to output formats.

## Required Development Workflow

**CRITICAL**: Always run these commands before committing:

```bash
uv sync                    # Install dependencies
uv run prek run --all-files  # Lint (ruff) + type check (ty)
uv run pytest              # Run tests
```

**All must pass** - this is enforced by CI.

## Documentation Requirements

**CRITICAL**: These docs must be kept up to date with all work:

### `docs/architecture.md`
- Live updated architectural overview
- Must reflect current system design
- Update when architecture changes

### `docs/decisions/`
- Architecture Decision Records (ADRs)
- Format: `NNN-short-name.md` (e.g., `001-mvp-scope.md`)
- Record *why* core decisions were made
- New architectural decisions require new files
- Not every small choice - only significant architectural decisions

**When to create an ADR:**
- Choosing between multiple valid approaches
- Scope decisions (what's in/out)
- Technology choices
- Pattern decisions that affect multiple components

## Repository Structure

| Path | Purpose |
|------|---------|
| `src/colin/` | Library source code (Python ≥ 3.10) |
| `├─compiler/` | Compilation engine and context |
| `├─extensions/` | Jinja extensions ({% llm %}, filters) |
| `├─plugins/` | Input, output, materialization plugins |
| `├─llm/` | LLM provider interface and implementations |
| `tests/` | Comprehensive pytest suite |
| `docs/` | Architecture docs and ADRs |

## Testing Standards

- Every test: atomic, self-contained, single functionality
- Use parameterization for multiple examples of same functionality
- Use separate tests for different functionality pieces
- **ALWAYS** put imports at the top of the file, not in the test body
- **NEVER** add `@pytest.mark.asyncio` to tests - `asyncio_mode = "auto"` is set globally
- **ALWAYS** run pytest after significant changes

## Code Standards

- Python ≥ 3.10 with full type annotations
- Use `from __future__ import annotations` only where needed (files with forward references, TYPE_CHECKING blocks, or complex type annotations)
- **ALWAYS** put imports at module level (no local imports inside functions)
- Minimize `# type: ignore` - fix types properly instead
- Follow existing patterns and maintain consistency
- Prioritize readable, understandable code - clarity over cleverness
- Never use bare `except` - be specific with exception types
- Each feature needs corresponding tests

## Git & Commits

- Never force-push on collaborative repos
- Keep commit messages brief - just headlines
- Run checks before committing
- Never amend commits

## Writing Style

- Be brief and to the point
- **NEVER** use "This isn't..." or "not just..." constructions
- State what something IS directly
