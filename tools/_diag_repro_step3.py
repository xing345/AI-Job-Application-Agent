"""逐步复现 step3 动作，定位崩溃点。"""
import asyncio
from pathlib import Path
from src.browser_agent.mcp_client import MCPBrowser

PROFILE = str(Path("data/browser_profile_mcp").resolve())
URL = "https://jobs.bytedance.com/campus/resume/7698959353864505653/apply?spread=DWA3PQP"

# step3 的动作（action, target, text）
ACTS = [
    ("click", "e515", ""),
    ("type", "e261", "2023-09"),
    ("type", "e272", "2027-06"),
    ("click", "e287", ""),
    ("type", "e306", "重庆移通学院"),
    ("click", "e317", ""),
    ("type", "e334", "软件工程学院"),
    ("type", "e346", "软件工程"),
    ("click", "e421", ""),
]


async def main():
    async with MCPBrowser(user_data_dir=PROFILE, headless=False) as b:
        await b.navigate(URL)
        await b.wait_for(time=3)
        # 复现 step1 前置：展开城市下拉(不选) + 上传简历 + 基本信息
        print("== step1 前置 ==")
        print("click e112:", "OK" if await b.click("e112") else "?")
        await b.wait_for(time=1)
        print("upload e140:", (await b.click("e140"))[-60:].replace("\n", " "))
        resume = str(Path("data/resume.pdf").resolve())
        print("file set:", (await b.upload([resume]))[:60].replace("\n", " "))
        await b.wait_for(time=1)
        await b.type("e160", "张亚辉")
        await b.type("e181", "15638108926")
        await b.type("e193", "313206376@qq.com")
        await b.wait_for(time=1)
        print("== step3 ==")
        for i, (a, t, txt) in enumerate(ACTS):
            try:
                if a == "click":
                    out = await b.click(t)
                else:
                    out = await b.type(t, txt)
                modal = "Modal state" in out or "modal" in out.lower()
                print(f"[{i}] {a} {t} OK modal={modal}")
                await b.wait_for(time=1)
            except Exception as e:
                print(f"[{i}] {a} {t} FAILED: {type(e).__name__}: {e}")
                break
        await b.wait_for(time=2)


asyncio.run(main())
