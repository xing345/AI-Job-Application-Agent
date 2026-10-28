"""fill 上海后，完整快照找建议项 ref。"""
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
        Path("tools/_city_filled.txt").write_text(snap, encoding="utf-8")
        lines = snap.splitlines()
        for i, line in enumerate(lines):
            if "上海" in line:
                # 打印前后几行
                for j in range(max(0, i-3), min(len(lines), i+4)):
                    print(lines[j])
                print("----")
        await b.wait_for(time=1)


asyncio.run(main())
