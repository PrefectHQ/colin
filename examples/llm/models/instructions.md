---
name: Instructions Example
description: Demonstrates using instructions (system prompts) to control LLM behavior
---

# Instructions Example

This document demonstrates how to use the `instructions` parameter to control LLM behavior with system prompts.

## Source Content

{{ ref('source.md').content }}

---

## Without Instructions

**Summary**: {{ ref('source.md') | llm_extract('a brief one-sentence summary of the feedback') }}

---

## With Pirate Instructions

**Pirate Summary**: {{ ref('source.md') | llm_extract('a brief one-sentence summary of the feedback', instructions='Talk like a pirate. Use "Arrr" and pirate vocabulary.') }}

---

## LLM Block with Instructions

{% llm instructions='Talk like a pirate. Use "Arrr" and pirate vocabulary.' %}
Summarize this product feedback in one sentence: {{ ref('source.md').content }}
{% endllm %}
