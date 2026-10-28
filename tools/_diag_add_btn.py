"""拿完整字节表单快照，保存到文件，分析"添加"按钮。"""
import asyncio
from pathlib import Path
from src.browser_agent.mcp_client import MCPBrowser

PROFILE = str(Path("data/browser_profile_mcp").resolve())
URL = "https://jobs.bytedance.com/campus/resume/7698959353864505653/apply?spread=DWA3PQP"


async def main():
    async with MCPBrowser(user_data_dir=PROFILE, headless=False) as b:
        await b.navigate(URL)
        await b.wait_for(time=4)
        snap = await b.snapshot()
        Path("tools/_form_snapshot.txt").write_text(snap, encoding="utf-8")
        print("saved len:", len(snap))
        for line in snap.splitlines():
            if "添加" in line or "button" in line:
                print(line.strip()[:120])
        await b.wait_for(time=1)


asyncio.run(main())
