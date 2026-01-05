---
name: Welcome
description: A polished welcome document demonstrating refs
---

# Welcome to {{ vars.project_name }}

{{ ref('project-info').content }}

---

## What is Colin?

Colin (**Co**ntext **Lin**eage) compiles interconnected documents into outputs your
agents can use. You just saw two of its core features in action:

**Variables** — The project name, description, and author above came from `vars`
defined in `colin.toml`. Colin prompted you for these when you ran `colin init`.

**References** — This document pulled in content from `project-info.md` using
`ref('project-info')`. Colin automatically resolves dependencies and compiles
documents in the right order.

## Next Steps

1. **Explore your project**
   - `models/` contains your source documents
   - `output/` contains compiled results
   - `colin.toml` configures variables, providers, and more

2. **Add an LLM block** — Edit a model and add:
   ```
   {%- raw %}
   {% llm %}
   Summarize this document in one sentence.
   {% endllm %}
   {% endraw -%}
   ```
   Then run `colin run` again.

3. **Learn more** — Visit https://github.com/jlowin/colin

Happy building!
