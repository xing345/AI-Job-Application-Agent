"""验证简历上传：先 file_upload 注册，再 click 选择文件。"""
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
        print("== 先注册文件 ==")
        print((await b.upload([RESUME]))[:200])
        print("== 再点选择文件 e140 ==")
        print((await b.click("e140"))[:300])
        await b.wait_for(time=3)
        snap = await b.snapshot()
        # 找简历区域附近是否显示文件名
        for line in snap.splitlines():
            if "resume" in line.lower() or ".pdf" in line.lower() or "重新上传" in line or "简历" in line:
                print("UPLOAD?", line.strip()[:100])
        await b.wait_for(time=1)


asyncio.run(main())
