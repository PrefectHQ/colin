---
name: Private Generator
description: A private generator that creates public outputs
---

# Private Generator

This document is private (underscore prefix) but creates public outputs.

{% file "public/api-spec.json" format="json" publish=true %}
## openapi
3.0.0

## info
### title
Example API

### version
1.0.0

## paths
### /health
#### get
##### summary
Health check endpoint
{% endfile %}

{% file "internal/debug-config.json" format="json" publish=false %}
## debug
true

## trace_level
verbose
{% endfile %}

Generator complete.
