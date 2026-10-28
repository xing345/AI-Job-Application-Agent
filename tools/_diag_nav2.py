"""navigate 完整输出 + 连续监测 URL。"""
import asyncio
from pathlib import Path
from src.browser_agent.mcp_client import MCPBrowser

URL = "https://jobs.bytedance.com/campus/resume/7698959353864505653/apply?spread=DWA3PQP"
PROFILE = str(Path("data/browser_profile").resolve())


async def main():
    async with MCPBrowser(user_data_dir=PROFILE, headless=False) as b:
        out = await b.navigate(URL)
        print("FULL NAV OUT:\n", out)
        for i in range(6):
            r = await b.call("browser_evaluate",
                             {"function": "() => location.href"})
            print(f"t{i}:", [l for l in r.splitlines() if "http" in l or "about" in l][:2])
            await b.wait_for(time=1)


asyncio.run(main())
