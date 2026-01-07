---
name: Welcome Message
description: Demonstrates ref() and LLM blocks
---

# Welcome

{{ ref('greeting.md').content }}

---

You just saw an example of `ref()` pulling in content from another document.
Colin automatically compiles documents in the right order based on their dependencies.

## Translation for French Users

{% llm %}
Translate this greeting message for French users of the Colin library:

{{ ref('greeting.md').content }}

The translation should feel welcoming and appropriate for a technical audience.
{% endllm %}
