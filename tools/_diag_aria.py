"""检查 MCP profile 是否已登录：直接打开表单 URL。"""
import asyncio
from pathlib import Path
from src.browser_agent.mcp_client import MCPBrowser

PROFILE = str(Path("data/browser_profile_mcp").resolve())
URL = "https://jobs.bytedance.com/campus/resume/7698959353864505653/apply?spread=DWA3PQP"


async def main():
    async with MCPBrowser(user_data_dir=PROFILE, headless=False) as b:
        await b.navigate(URL)
        await b.wait_for(time=4)
        r = await b.call("browser_evaluate", {"function": "() => location.href"})
        print("URL:", [l for l in r.splitlines() if "http" in l or "about" in l][:1])
        snap = await b.snapshot()
        print("SNAP_LEN:", len(snap))
        print(snap[:1500])
        await b.wait_for(time=1)


asyncio.run(main())
