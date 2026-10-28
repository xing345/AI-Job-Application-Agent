"""用全新 profile 目录测试 MCP 是否稳定。"""
import asyncio
from pathlib import Path
from src.browser_agent.mcp_client import MCPBrowser

URL = "https://jobs.bytedance.com/campus/resume/7698959353864505653/apply?spread=DWA3PQP"
NEW = str(Path("data/browser_profile_mcp_test").resolve())


async def main():
    async with MCPBrowser(user_data_dir=NEW, headless=True) as b:
        await b.navigate(URL)
        for i in range(5):
            r = await b.call("browser_evaluate", {"function": "() => location.href"})
            url = [l for l in r.splitlines() if "http" in l or "about" in l]
            print(f"t{i}:", url[:1])
            await b.wait_for(time=1)


asyncio.run(main())
