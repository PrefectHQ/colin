"""Simple MCP server for the everything example."""

from fastmcp import FastMCP

mcp = FastMCP("demo")


@mcp.tool()
def calculate(operation: str, a: float, b: float) -> float:
    """Perform a calculation."""
    if operation == "add":
        return a + b
    elif operation == "multiply":
        return a * b
    else:
        return 0


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
