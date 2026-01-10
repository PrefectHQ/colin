---
name: User Generator
description: Demonstrates generating multiple files from a single source
---

# User Generator

This document generates individual user profile files dynamically.

{% for user in [{"name": "Alice", "role": "Engineer", "team": "Platform"}, {"name": "Bob", "role": "Designer", "team": "Product"}, {"name": "Charlie", "role": "Manager", "team": "Platform"}] %}
{% file "profiles/" ~ user.name | lower ~ ".md" %}
# {{ user.name }}

**Role:** {{ user.role }}
**Team:** {{ user.team }}

{% section bio %}
{{ user.name }} is a {{ user.role }} on the {{ user.team }} team.
{% endsection %}
{% endfile %}
{% endfor %}

## Generated Files

The following user profiles were generated:
- profiles/alice.md
- profiles/bob.md
- profiles/charlie.md
