"""城市搜索：输入上海，看选项。"""
import asyncio
from pathlib import Path
from src.browser_agent.mcp_client import MCPBrowser

PROFILE = str(Path("data/browser_profile_mcp").resolve())
URL = "https://jobs.bytedance.com/campus/resume/7698959353864505653/apply?spread=DWA3PQP"


async def main():
    async with MCPBrowser(user_data_dir=PROFILE, headless=False) as b:
        await b.navigate(URL)
        await b.wait_for(time=3)
        await b.click("e112")
        await b.wait_for(time=1)
        await b.type("e117", "上海")
        await b.wait_for(time=2)
        snap = await b.snapshot()
        lines = snap.splitlines()
        capture = False
        for line in lines:
            if "combobox" in line:
                capture = True
            if capture:
                print(line)
            if capture and "简历" in line:
                break
        await b.wait_for(time=1)


asyncio.run(main())
