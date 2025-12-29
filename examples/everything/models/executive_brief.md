---
name: Executive Brief
description: High-level summary for leadership
---
# Executive Brief: Q1 2025 Planning

## TL;DR
{{ ref('recommendations') | extract('Summarize the top 3 priorities in one sentence each') }}

## Current State
{{ ref('goal_status') | extract('Give a one-paragraph executive summary of goal progress') }}

## Detailed Recommendations
{{ ref('recommendations').content }}

---

## Appendix: Raw Data
<details>
<summary>Click to expand source data</summary>

{{ ref('data').content }}
</details>
