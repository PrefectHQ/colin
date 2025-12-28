"""Test MCP server for e2e tests."""

from fastmcp import FastMCP

mcp = FastMCP("colin-test")


@mcp.resource(uri="colin://hello")
def hello() -> str:
    return "Hello, world!"


@mcp.resource(uri="colin://goodbye/{name}")
def goodbye(name: str) -> str:
    return f"Goodbye, {name}!"


@mcp.prompt()
def greet() -> str:
    """A simple greeting prompt."""
    return "Please greet the user warmly."


@mcp.prompt()
def translate(language: str, tone: str = "casual") -> str:
    """A translation prompt with parameters."""
    return f"Translate the following text to {language} using a {tone} tone."


if __name__ == "__main__":
    mcp.run()
