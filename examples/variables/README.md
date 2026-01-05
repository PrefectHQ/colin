# Variables Example

Demonstrates project variables with typed configuration and interactive prompting.

## Usage

```bash
# Interactive - prompts for author
colin run

# Provide via CLI
colin run --var author="Jane Doe"

# Override defaults
colin run --var author="Jane" --var env=prod --var debug=true

# Or via environment
COLIN_VAR_AUTHOR="Jane" colin run
```

## Variables

| Name | Type | Default | Prompt |
|------|------|---------|--------|
| `author` | string | - | "Who is the author?" |
| `env` | string | `dev` | - |
| `debug` | bool | `false` | - |
