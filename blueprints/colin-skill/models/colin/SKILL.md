---
name: colin
description: Use Colin to compile context from live sources into agent skills
colin:
  template: false
---

# Colin

Colin is a context compiler that transforms interconnected source documents into outputs agents can use. It resolves dependencies between documents, applies transformations including LLM calls, and produces compiled context.

## When to Use Colin

Use Colin when the user wants to:

- Create or update agent skills from live sources
- Compile documentation that references other files
- Generate context that pulls from GitHub, Notion, or MCP servers
- Keep skills fresh as source material changes

## Quick Start

```bash
# Create a new project
colin init my-project
cd my-project

# Edit models/hello.md, then compile
colin run

# Output appears in output/
```

## Project Structure

```
my-project/
├── colin.toml       # Configuration
├── models/          # Source templates
│   └── hello.md
└── output/          # Compiled output
    └── hello.md
```

## Key Concepts

- **Models**: Source templates in `models/` that can reference each other
- **Refs**: `{{ ref('other-doc') }}` pulls in compiled content from another document
- **Outputs**: Compiled files written to `output/` or a skill directory
- **Manifests**: Track what files belong to which project for clean updates
