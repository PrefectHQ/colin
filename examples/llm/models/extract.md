---
name: Extract Example
description: Demonstrates the extract filter for extracting information from content
---

# Extract Example

This document demonstrates how to use the `extract()` filter to pull specific information from content.

## Source Content

{{ ref('source.md').content }}

---

## Extracted Information

**Main Complaints**: {{ ref('source.md') | llm_extract('the main complaints or negative feedback mentioned') }}
