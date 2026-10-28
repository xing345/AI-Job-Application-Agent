"""最简城市选择：只展开 -> 只点北京，不做其他操作。"""
import asyncio
import re
from pathlib import Path
from src.browser_agent.mcp_client import MCPBrowser

PROFILE = str(Path("data/browser_profile_mcp").resolve())
URL = "https://jobs.bytedance.com/campus/resume/7698959353864505653/apply?spread=DWA3PQP"

CHECK = """() => {
  const sel = document.querySelector('[class*="city-select"]');
  return sel ? sel.textContent.trim().slice(0,60) : null;
}"""


async def main():
    async with MCPBrowser(user_data_dir=PROFILE, headless=False) as b:
        await b.navigate(URL)
        await b.wait_for(time=3)
        # 第一步：只展开
        await b.click("e112")
        await b.wait_for(time=1)
        # 重新快照，确认 option
        snap = await b.snapshot()
        m = re.search(r'option "北京" \[ref=(e\d+)\]', snap)
        ref = m.group(1) if m else None
        print("展开后北京 ref:", ref)
        # 第二步：只点北京
        if ref:
            out = await b.click(ref)
            print("click tail:", out[-150:])
        await b.wait_for(time=2)
        r = await b.evaluate(CHECK)
        print("城市区域:", r)
        await b.wait_for(time=1)


asyncio.run(main())
