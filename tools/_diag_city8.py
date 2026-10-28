"""查 dropdown 所有城市选项（含不可见）。"""
import asyncio
from pathlib import Path
from src.browser_agent.mcp_client import MCPBrowser

PROFILE = str(Path("data/browser_profile_mcp").resolve())
URL = "https://jobs.bytedance.com/campus/resume/7698959353864505653/apply?spread=DWA3PQP"

JS = """() => {
  const items = [...document.querySelectorAll('.atsx-select-dropdown-menu-item')];
  return {
    total: items.length,
    all: items.map(i => (i.textContent||'').trim()),
    shanghai: items.filter(i => i.textContent.includes('上海')).map(i => ({
      cls: i.className.slice(0,60), vis: i.getBoundingClientRect().height}))
  };
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
        print(r.split("### Ran")[0][:2500])
        await b.wait_for(time=1)


asyncio.run(main())
