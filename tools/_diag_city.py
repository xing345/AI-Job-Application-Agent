"""展开意向城市下拉，分析结构。"""
import asyncio
from pathlib import Path
from src.browser_agent.mcp_client import MCPBrowser

PROFILE = str(Path("data/browser_profile_mcp").resolve())
URL = "https://jobs.bytedance.com/campus/resume/7698959353864505653/apply?spread=DWA3PQP"


async def main():
    async with MCPBrowser(user_data_dir=PROFILE, headless=False) as b:
        await b.navigate(URL)
        await b.wait_for(time=3)
        out = await b.click("e112")
        print("CLICK e112 tail:", out[-300:])
        await b.wait_for(time=2)
        snap = await b.snapshot()
        Path("tools/_city_snap.txt").write_text(snap, encoding="utf-8")
        # 打印城市区域（e102 附近）
        lines = snap.splitlines()
        capture = False
        for line in lines:
            if "意向城市" in line or "请选择意向城市" in line:
                capture = True
            if capture:
                print(line)
            if capture and ("简历" in line):
                break
        await b.wait_for(time=1)


asyncio.run(main())
