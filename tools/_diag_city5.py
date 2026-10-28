"""输入上海后，用 evaluate 检查 DOM 选项。"""
import asyncio
from pathlib import Path
from src.browser_agent.mcp_client import MCPBrowser

PROFILE = str(Path("data/browser_profile_mcp").resolve())
URL = "https://jobs.bytedance.com/campus/resume/7698959353864505653/apply?spread=DWA3PQP"

JS = """() => {
  const all = [...document.querySelectorAll('*')];
  const out = [];
  for (const e of all) {
    const t = (e.textContent||'').trim();
    if (t === '上海' && e.children.length === 0) {
      const r = e.getBoundingClientRect();
      out.push({tag: e.tagName, cls: (e.className||'').toString().slice(0,60),
                role: e.getAttribute('role'), y: Math.round(r.y), x: Math.round(r.x)});
    }
  }
  return out;
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
        print(r[:1500])
        await b.wait_for(time=1)


asyncio.run(main())
