---
name: Summary
description: Demonstrates LLM blocks and extract filter
---

# Summary Example

Here's some content to work with:

{{ ref('greeting').content }}



## Extracted Info

{{ ref('greeting') | llm_extract('the main message in one sentence') }}

## LLM-Generated Content

{% llm %}
Given this greeting:
{{ ref('greeting').content }}

Write a haiku about being welcomed.
{% endllm %}
