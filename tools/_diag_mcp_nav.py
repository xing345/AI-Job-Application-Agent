"""逐步诊断 MCP 导航：navigate → 查 URL → snapshot，不交给 LLM。"""
import asyncio
from pathlib import Path
from src.browser_agent.mcp_client import MCPBrowser

URL = "https://jobs.bytedance.com/campus/resume/7698959353864505653/apply?spread=DWA3PQP"
PROFILE = str(Path("data/browser_profile").resolve())


async def main():
    async with MCPBrowser(user_data_dir=PROFILE, headless=False) as b:
        print(">> navigate")
        out = await b.navigate(URL)
        print("NAV_OUT:", out[:300])
        await b.wait_for(time=3)
        loc = await b.call("browser_evaluate", {"function": "() => ({url: location.href, title: document.title})"})
        print("AFTER_NAV:", loc[:300])
        snap = await b.snapshot()
        print("SNAP_LEN:", len(snap))
        print(snap[:1200])
        await b.wait_for(time=2)


asyncio.run(main())
