# Hello World Example

A minimal Colin project demonstrating the core features.

## Files

- `models/greeting.md` - A simple base document
- `models/welcome.md` - Uses `ref()` to include the greeting
- `models/summary.md` - Uses `ref()`, `| llm_extract()`, and `{% llm %}` blocks

## Run It

```bash
cd examples/hello_world
colin run
```

## Output

After compiling, check the `output/` directory. The `summary.md` file will contain real LLM responses.

Set your API key before running:

```bash
export ANTHROPIC_API_KEY=your-key-here
```

## What to Notice

1. **Dependency order**: `greeting` compiles first because `welcome` and `summary` depend on it
2. **ref() inclusion**: The greeting content appears inline in `welcome.md`
3. **LLM caching**: Run `colin run` twice—the second run uses cached LLM responses
