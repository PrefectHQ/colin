# ADR 007: Implicit Previous Output (No Explicit Variable)

**Status**: Accepted
**Date**: 2024-12-27

## Context

The original design had users write `{{ previous }}` in templates to access the prior output of an LLM block:

```jinja
{% llm id="analysis" %}
Previous: {{ previous }}
New data: {{ ref('sources/data') }}
{% endllm %}
```

This requires template authors to remember to include `{{ previous }}` and format it correctly.

## Decision

Remove the explicit `{{ previous }}` variable. Instead, LLM calls with stable IDs automatically receive their prior output as part of the prompt context. The user never writes `{{ previous }}`.

### How It Works

1. LLM call has a stable ID (manual like `id='features'` or auto-generated)
2. Cache lookup by ID finds previous output
3. If cache hit (same input hash): return cached output, no LLM call
4. If cache miss (input changed): call LLM with previous output in context

```python
# For | extract() filter:
{{ content | extract('feature requests', id='features') }}

# Internally, LLM prompt includes:
# "Previous output for this extraction (maintain if still accurate):
#  {cached_output}"
```

### For `{% llm %}` Blocks

```jinja
{% llm id="analysis" %}
Analyze this data: {{ ref('sources/data') }}
{% endllm %}

{# LLM automatically sees its previous output for id="analysis" #}
```

## Rationale

1. **Simpler templates**: No `{{ previous }}` boilerplate
2. **Consistent behavior**: All LLM calls with IDs work the same way
3. **Less error-prone**: Can't forget to include previous output
4. **Separation of concerns**: Stability is a caching concern, not a template concern

## Consequences

- Template authors don't control how previous output is formatted
- The caching layer is responsible for stability prompts
- Templates are cleaner and more focused on the core logic
