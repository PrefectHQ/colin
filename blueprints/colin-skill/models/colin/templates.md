---
name: colin-templates
description: How to write Colin templates
colin:
  template: false
---

# Templates

Colin uses Jinja2 templates. Source files in `models/` are templates that compile to output.

## References

Pull content from other documents:

```markdown
# My Document

{{ ref('other-doc').content }}
```

The referenced document compiles first, then its content is available.

## Variables

Define in `colin.toml`:

```toml
[vars]
api_url = "https://api.example.com"
timeout = 30
```

Use in templates:

```markdown
API endpoint: {{ colin.var.api_url }}
Timeout: {{ colin.var.timeout }} seconds
```

Override with CLI:

```bash
colin run --var api_url=https://staging.example.com
```

## File Blocks

Generate multiple files from one template:

```markdown
---
colin:
  output:
    publish: false
---

{% file "api/overview.md" publish=true %}
# API Overview
Content here...
{% endfile %}

{% file "api/endpoints.md" publish=true %}
# Endpoints
More content...
{% endfile %}
```

## GitHub Provider

Pull from GitHub repositories:

```toml
[[providers.github]]
token = "${GITHUB_TOKEN}"
```

```markdown
{{ colin.github.file('owner/repo', 'README.md').content }}
```

## MCP Resources

Access MCP server resources:

```toml
[[providers.mcp]]
name = "linear"
command = "npx"
args = ["-y", "@anthropic/mcp-server-linear"]
```

```markdown
{{ colin.mcp.linear.resource('issues/active').content }}
```

## Skills Output

Write directly to Claude's skills folder:

```toml
[project.output]
target = "claude-skill"
scope = "user"  # ~/.claude/skills/
```

Or project-scoped:

```toml
[project.output]
target = "claude-skill"
scope = "project"  # .claude/skills/
```
