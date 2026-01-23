# Colin CLI Commands

Colin is a context compiler that transforms interconnected documents into compiled outputs for AI agents. Here are the essential commands.

## `colin init`

Create a new Colin project in the current directory:

```bash
colin init
```

This creates:
- `colin.toml` - project configuration
- `models/` - directory for your source documents

## `colin run`

Compile a project. Run from a directory containing `colin.toml`:

```bash
colin run                          # Compile current project
colin run path/to/project          # Compile specific project
colin run --output ./dist          # Override output directory
colin run --quiet                  # Suppress progress output
colin run --no-cache               # Force recompile everything
colin run --var api_key=secret     # Pass variable overrides
```

Colin incrementally compiles only changed documents, making subsequent runs fast.

## `colin update`

Update outputs from their source project. Run from an output directory (one containing `.colin-manifest.json`):

```bash
colin update                       # Update current directory
colin update ~/.claude/skills/my-skill  # Update specific output
colin update --no-cache            # Force full rebuild
colin update --var key=new_value   # Override stored variables
```

The manifest stores the source project location and any `--var` overrides, so you can update outputs without knowing where the source lives.

## `colin skills update`

Update all Colin-managed skills:

```bash
colin skills update                # Update ~/.claude/skills/
colin skills update ./my-skills    # Update custom directory
```

Scans for subdirectories with `.colin-manifest.json` and runs `colin update` on each in parallel.

## `colin clean`

Remove stale files from output:

```bash
colin clean                        # Clean output/ only
colin clean --all                  # Also clean .colin/compiled/
```