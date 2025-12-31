---
name: Recommendations
description: Prioritized action items based on analysis
---
# Strategic Recommendations

## Analysis Summary
{{ ref('analysis').content }}

## Goal Status
{{ ref('goal_status') | llm_extract('Which goals are at risk or behind?') }}

## Recommended Actions

{% llm %}
Based on the pain points and goal gaps identified above, provide 3-5 prioritized recommendations.

For each recommendation:
1. What to do
2. Why it matters (link to specific pain point or goal)
3. Expected impact

Be specific and actionable.
{% endllm %}
