---
title: Sprint Status
---
# Current Sprint

{% set in_progress = colin.linear.issues(state="In Progress", limit=10) %}
{% set todo = colin.linear.issues(state="Todo", limit=10) %}

## In Progress ({{ in_progress | length }})

{% for issue in in_progress %}
- **{{ issue.identifier }}**: {{ issue.title }}
  - Assignee: {{ issue.assignee or "Unassigned" }}
{% endfor %}

## Todo ({{ todo | length }})

{% for issue in todo %}
- {{ issue.identifier }}: {{ issue.title }}
{% endfor %}
