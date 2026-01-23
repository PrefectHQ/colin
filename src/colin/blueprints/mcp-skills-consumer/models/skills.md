---
colin:
  output:
    publish: false
---
{% set server = colin.mcp.source %}

{# Discover and download all skills from the MCP server #}
{% for skill in server.list_skills() %}

{# Download each file in the skill #}
{% for file in skill.files %}
{% set file_uri = 'skill://' ~ skill.name ~ '/' ~ file.path %}
{% file skill.name ~ "/" ~ file.path publish=true %}
{{ server.resource(file_uri).content }}
{% endfile %}
{% endfor %}

{% endfor %}
