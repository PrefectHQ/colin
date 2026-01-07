---
name: Goal Status
description: Assessment of progress toward goals
---
# Goal Progress Assessment

Based on current metrics and stated objectives:

**Current Data:**
{{ ref('data.md').content }}

**Goals:**
{{ ref('goals.md').content }}

{% llm %}
Compare the current metrics from the data above against the stated goals.
For each goal, indicate whether we are:
- On Track (green)
- At Risk (yellow)
- Behind (red)

Format as a markdown table with columns: Goal | Status | Gap/Progress
{% endllm %}
