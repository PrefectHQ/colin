# Hello World Example

A minimal Colin project demonstrating the core features.

## Files

- `models/greeting.md` - A simple base document
- `models/welcome.md` - Uses `ref()` to include the greeting
- `models/summary.md` - Uses `ref()`, `| extract()`, and `{% llm %}` blocks

## Run It

```bash
cd examples/hello_world
cbt run
```

## Output

After compiling, check the `target/` directory. The `summary.md` file will contain stub LLM responses (the MVP uses a stub provider).

## What to Notice

1. **Dependency order**: `greeting` compiles first because `welcome` and `summary` depend on it
2. **ref() inclusion**: The greeting content appears inline in `welcome.md`
3. **LLM tracking**: Run `cbt status` to see LLM call metadata
