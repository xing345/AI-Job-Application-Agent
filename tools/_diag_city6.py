"""检查 atsx 下拉面板和 input 结构。"""
import asyncio
from pathlib import Path
from src.browser_agent.mcp_client import MCPBrowser

PROFILE = str(Path("data/browser_profile_mcp").resolve())
URL = "https://jobs.bytedance.com/campus/resume/7698959353864505653/apply?spread=DWA3PQP"

JS = """() => {
  const inputs = [...document.querySelectorAll('input')].map(i => ({
    cls: (i.className||'').slice(0,50), ph: i.placeholder, val: i.value}));
  const panels = [...document.querySelectorAll('[class*="atsx-select"]')].map(p => ({
    cls: (p.className||'').slice(0,55),
    vis: Math.round(p.getBoundingClientRect().height),
    txt: (p.textContent||'').trim().slice(0,40)}));
  return {inputs, panels: panels.slice(0,20)};
}"""


async def main():
    async with MCPBrowser(user_data_dir=PROFILE, headless=False) as b:
        await b.navigate(URL)
        await b.wait_for(time=3)
        await b.click("e112")
        await b.wait_for(time=1)
        await b.type("e117", "上海")
        await b.wait_for(time=2)
        r = await b.call("browser_evaluate", {"function": JS})
        # 只打印 Result 部分
        print(r.split("### Ran")[0][:2500])
        await b.wait_for(time=1)


asyncio.run(main())
