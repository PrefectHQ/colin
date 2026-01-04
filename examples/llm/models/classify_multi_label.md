---
name: Multi-Label Classify Example
description: Demonstrates the classify filter with multi-label classification
---

# Multi-Label Classify Example

This document demonstrates how to use the `classify()` filter with `multi=True` to categorize content into multiple labels.

## Source Content

{{ ref('source.md').content }}

---

## Multi-Label Classification Result

**Topics**: {{ ref('source.md') | llm_classify(labels=['interface', 'performance', 'pricing', 'support', 'features', 'bugs'], multi=True) }}
