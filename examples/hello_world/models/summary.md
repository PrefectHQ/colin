---
name: Summary
description: Demonstrates LLM blocks and extract filter
---

# Summary Example

Here's some content to work with:

{{ ref('greeting').content }}



## Extracted Info

{{ ref('greeting') | extract('the main message in one sentence') }}

## LLM-Generated Content

{% llm %}
Given this greeting:
{{ ref('greeting').content }}

Write a haiku about being welcomed.
{% endllm %}

## With Explicit Model

{% llm model="anthropic:claude-sonnet-4-5" %}
Translate this greeting to French:
{{ ref('greeting').content }}
{% endllm %}
