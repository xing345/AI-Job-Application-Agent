"""测试连接 Playwright MCP 服务器并列出工具。"""
import asyncio
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CLI = r"C:\Users\Administrator\AppData\Local\Doubao\User Data\sandbox_runtime\bases\772984f6fd3a8ae0ae7d2422cd7c2bfa\node\node_modules\@playwright\mcp\cli.js"
PROFILE = r"D:\x\ai agent\data\browser_profile"


async def main():
    params = StdioServerParameters(
        command="node",
        args=[CLI, "--user-data-dir", PROFILE, "--headless"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f"共 {len(tools.tools)} 个工具:")
            for t in tools.tools:
                desc = (t.description or "").split("\n")[0][:70]
                print(f"  {t.name:28} {desc}")


try:
    asyncio.run(main())
except Exception as e:
    print("ERROR:", e)
    sys.exit(1)
