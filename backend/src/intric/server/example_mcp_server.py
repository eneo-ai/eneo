# pyright: reportMissingImports=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownMemberType=false
# pyright: reportUntypedFunctionDecorator=false
"""Example MCP server using FastMCP - requires 'pip install fastmcp' for local testing."""
from fastmcp import FastMCP

# Create a basic server instance
mcp = FastMCP(
    name="MathServer",
    instructions="""
        This server provides math helper tools.
        Call add_two_numbers() to add two numbers.
    """,
)

@mcp.tool
def add_two_numbers(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

# Run the server when executed
if __name__ == "__main__":
    mcp.run()
