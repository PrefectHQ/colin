---
colin:
  output:
    publish: false
---
{% set server = colin.mcp.source.server_info() %}
{% for tool in colin.mcp.source.list_tools() %}
{% set server_name = vars.mcp_provider_name | default(server.name) %}
{% set skill_name = server_name | lower | replace(" ", "-") %}
{% file skill_name ~ "/" ~ tool.name ~ ".md" publish=true %}

# {{ tool.title or tool.name }}

{% section summary %}
{% llm model="anthropic:claude-haiku-4-5" id="tool-summary-" ~ tool.name %}
Write a 1-2 sentence description of this tool, including when you would use it.

Tool name: {{ tool.name }}
Title: {{ tool.title or "None" }}
Description: {{ tool.description or "None" }}
Input schema: {{ tool.inputSchema | tojson }}
Output schema: {{ tool.outputSchema | tojson if tool.outputSchema else "None" }}
{% endllm %}
{% endsection %}
{% if tool.description %}

{{ tool.description }}
{% endif %}

## Parameters

{% if tool.inputSchema.properties %}
```json
{{ tool.inputSchema | tojson(indent=2) }}
```
{% else %}
No parameters.
{% endif %}

{% if tool.outputSchema %}

## Output

Returns: {{ tool.outputSchema.get('description', tool.outputSchema.get('type', 'object')) }}
{% endif %}
{% if vars.generate_scripts | default(true) %}

## Usage

To call this MCP tool without MCP access, use the included script:

```bash
python scripts/{{ tool.name }}.py '{"param": "value"}'
```

{% endif %}

## Server

This tool is provided by **{{ server.name or vars.mcp_provider_name or "the MCP server" }}**{% if server.instructions %} - {{ server.instructions }}{% endif %}

{% endfile %}
{% endfor %}
