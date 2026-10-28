"""诊断 MCP tabs：启动后、navigate 后分别列出 tab。"""
import asyncio
from pathlib import Path
from src.browser_agent.mcp_client import MCPBrowser

URL = "https://jobs.bytedance.com/campus/resume/7698959353864505653/apply?spread=DWA3PQP"
PROFILE = str(Path("data/browser_profile").resolve())


async def main():
    async with MCPBrowser(user_data_dir=PROFILE, headless=False) as b:
        print("== 启动后 tabs ==")
        print(await b.call("browser_tabs", {"action": "list"}))
        print("== navigate ==")
        await b.navigate(URL)
        await b.wait_for(time=3)
        print("== navigate 后 tabs ==")
        print(await b.call("browser_tabs", {"action": "list"}))


asyncio.run(main())
