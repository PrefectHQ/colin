---
name: Classify Example
description: Demonstrates the classify filter for categorizing content into predefined labels
---

# Classify Example

This document demonstrates how to use the `classify()` filter to categorize content into predefined labels.

## Source Content

{{ ref('source.md').content }}

---

## Classification Result

**Sentiment**: {{ ref('source.md') | llm_classify(labels=['positive', 'negative', 'neutral']) }}
