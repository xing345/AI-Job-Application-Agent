"""导出关键 MCP 工具的完整参数 schema。"""
import asyncio
import json
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CLI = r"C:\Users\Administrator\AppData\Local\Doubao\User Data\sandbox_runtime\bases\772984f6fd3a8ae0ae7d2422cd7c2bfa\node\node_modules\@playwright\mcp\cli.js"
WANT = {"browser_click", "browser_type", "browser_select_option", "browser_fill_form",
        "browser_file_upload", "browser_snapshot", "browser_navigate"}


async def main():
    params = StdioServerParameters(command="node", args=[CLI, "--headless"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            tools = await s.list_tools()
            for t in tools.tools:
                if t.name in WANT:
                    print(f"=== {t.name} ===")
                    print(json.dumps(t.input_schema, ensure_ascii=False, indent=2))


asyncio.run(main())
