---
colin:
  output:
    publish: false
  depends_on:
    - _tool-generator.md
---
{% if vars.generate_scripts | default(true) %}
{% set server = colin.mcp.source.server_info() %}
{% set server_name = vars.mcp_provider_name | default(server.name) %}
{% set skill_name = server_name | lower | replace(" ", "-") %}
{% for tool in colin.mcp.source.list_tools() %}
{% file skill_name ~ "/scripts/" ~ tool.name ~ ".py" publish=true %}
#!/usr/bin/env python3
"""Call the {{ tool.name }} MCP tool via FastMCP."""
import asyncio
import json
import sys
from fastmcp import Client

SERVER_COMMAND = "{{ colin.mcp.source.config().command }}"


async def main():
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    async with Client(SERVER_COMMAND) as client:
        result = await client.call_tool("{{ tool.name }}", args)
        # Format output for Claude
        if hasattr(result, "content"):
            for item in result.content:
                if hasattr(item, "text"):
                    print(item.text)
                else:
                    print(json.dumps(item, default=str))
        else:
            print(json.dumps(result, default=str, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
{% endfile %}
{% endfor %}
{% endif %}
