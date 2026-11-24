"""本地演示 MCP Server（stdio），用于冒烟测试。

启动方式由 MCP 客户端自动拉起：
    python scripts/demo_mcp_server.py
"""

from mcp.server.mcpserver import MCPServer

server = MCPServer("demo-digital-employee")


@server.tool()
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


@server.tool()
def echo(text: str) -> str:
    """Echo the input text."""
    return text


if __name__ == "__main__":
    server.run("stdio")
