# Creating a New Colin Project

When creating a new Colin project, start with `colin init`:

```bash
mkdir my-project && cd my-project
colin init
```

This creates:
- `colin.toml` - Project configuration
- `models/` - Directory for source documents

## colin.toml Configuration

### Basic Structure

```toml
[project]
name = "my-project"
model-path = "models"

[project.output]
path = "output"
```

| Setting | Description | Default |
| :------ | :---------- | :------ |
| `name` | Project name | Directory name |
| `model-path` | Source documents directory | `models` |
| `[project.output] path` | Output directory | `output` |

### Output Targets

For skills that install to Claude:

```toml
[project.output]
target = "claude-skill"
```

This writes to `~/.claude/skills/<project-name>/`.

### Variables

Variables are accessible in templates and can be overridden at runtime:

```toml
[vars]
api_key = "default-value"

[vars.timeout]
type = "int"
default = 30
optional = false
```

Override with `--var timeout=60` or `COLIN_VAR_TIMEOUT=60`.

### LLM Provider

Configure the default LLM for `{% llm %}` blocks:

```toml
[[providers.llm]]
model = "anthropic:claude-haiku-4-5"
instructions = "You are a helpful assistant."
```

### MCP Servers

Connect to MCP servers for external data:

```toml
[[providers.mcp]]
name = "github"
command = "uvx"
args = ["mcp-server-github"]
env = { GITHUB_TOKEN = "${GITHUB_TOKEN}" }
```

Access in templates with `colin.mcp.github.resource(...)`.

### GitHub Provider

Fetch files directly from GitHub repositories:

```toml
[[providers.github]]
name = "myrepo"
repo = "owner/repo"
token = "${GITHUB_TOKEN}"
```

Access in templates with `colin.github.myrepo.file("path/to/file.md").content`.