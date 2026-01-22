# Dynamic Files Example

Demonstrates generating multiple output files from a single source document using the `{% file %}` directive.

## What It Shows

- Creating multiple files from loops
- Generating different output formats (JSON, YAML, Markdown)
- Using sections within file blocks
- Private generators that produce public outputs

## Files

- `models/generator.md` - Loops over data to create individual profile files
- `models/config-builder.md` - Generates config files in JSON and YAML formats
- `models/_private-generator.md` - Private source that produces public outputs

## Run It

```bash
cd examples/dynamic_files
colin run
```

Check `output/` to see the generated files:
- `output/profiles/alice.md`, `bob.md`, `charlie.md`
- `output/config/app.json`, `app.yaml`

## The {% file %} Directive

Generate additional files from a single source:

```jinja
{% for user in users %}
{% file "profiles/" ~ user.name | lower ~ ".md" %}
# {{ user.name }}
{{ user.bio }}
{% endfile %}
{% endfor %}
```

Options:
- `format="json"` - Apply JSON renderer to the block
- `format="yaml"` - Apply YAML renderer
- `publish=true/false` - Override publish setting

Sections inside `{% file %}` blocks are scoped to that file and accessible via `ref("profiles/alice.md").sections.bio`.
