"""Simple MCP server for the mcp example."""

from fastmcp import FastMCP

mcp = FastMCP("demo")


@mcp.resource(uri="demo://greeting/{name}")
def greeting(name: str) -> str:
    """Get a personalized greeting."""
    return f"Hello, {name}! Welcome to the demo."


@mcp.prompt()
def summarize(style: str = "brief") -> str:
    """Summarization guidance."""
    return f"Summarize the following in a {style} style."


if __name__ == "__main__":
    mcp.run()
