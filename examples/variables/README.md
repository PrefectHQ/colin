# Variables Example

Demonstrates project variables with typed configuration.

## Usage

```bash
# Fails - author is required
colin run

# Works - provide required variable
colin run --var author="Jane Doe"

# Override defaults
colin run --var author="Jane" --var env=prod --var debug=true

# Or via environment
COLIN_VAR_AUTHOR="Jane" colin run
```

## Variables

| Name | Type | Default | Required |
|------|------|---------|----------|
| `author` | string | - | Yes |
| `env` | string | `dev` | No |
| `debug` | bool | `false` | No |
