"""验证简历上传：先 click 选择文件，再 file_upload。"""
import asyncio
from pathlib import Path
from src.browser_agent.mcp_client import MCPBrowser

PROFILE = str(Path("data/browser_profile_mcp").resolve())
RESUME = str(Path("data/resume.pdf").resolve())
URL = "https://jobs.bytedance.com/campus/resume/7698959353864505653/apply?spread=DWA3PQP"


async def main():
    async with MCPBrowser(user_data_dir=PROFILE, headless=False) as b:
        await b.navigate(URL)
        await b.wait_for(time=3)
        print("== 点选择文件 ==")
        print((await b.click("e140"))[-200:])
        print("== upload ==")
        print((await b.upload([RESUME]))[:300])
        await b.wait_for(time=3)
        snap = await b.snapshot()
        for line in snap.splitlines():
            if ".pdf" in line.lower() or "重新上传" in line or "替换" in line or "删除" in line:
                print("UPLOAD?", line.strip()[:100])
        await b.wait_for(time=1)


asyncio.run(main())
