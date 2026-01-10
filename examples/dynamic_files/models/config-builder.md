---
name: Config Builder
description: Generates configuration files in multiple formats
---

# Config Builder

This document demonstrates generating structured data files.

{% set app_config = {"name": "myapp", "version": "1.0.0", "port": 8080} %}

{% file "config/app.json" format="json" %}
## name
{{ app_config.name }}

## version
{{ app_config.version }}

## port
{{ app_config.port }}

## features
### logging
true

### metrics
true
{% endfile %}

{% file "config/app.yaml" format="yaml" %}
## name
{{ app_config.name }}

## version
{{ app_config.version }}

## settings
### debug
false

### max_connections
100
{% endfile %}

## Generated Configs

Configuration files generated:
- `config/app.json` - JSON format
- `config/app.yaml` - YAML format
