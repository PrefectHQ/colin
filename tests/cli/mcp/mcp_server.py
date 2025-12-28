"""Test MCP server for e2e tests."""

from fastmcp import FastMCP

mcp = FastMCP("colin-test")


@mcp.resource(uri="colin://hello")
def hello() -> str:
    return "Hello, world!"


@mcp.resource(uri="colin://goodbye/{name}")
def goodbye(name: str) -> str:
    return f"Goodbye, {name}!"


if __name__ == "__main__":
    mcp.run()
