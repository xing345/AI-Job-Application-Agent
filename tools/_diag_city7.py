"""原生触发输入，然后查下拉选项。"""
import asyncio
from pathlib import Path
from src.browser_agent.mcp_client import MCPBrowser

PROFILE = str(Path("data/browser_profile_mcp").resolve())
URL = "https://jobs.bytedance.com/campus/resume/7698959353864505653/apply?spread=DWA3PQP"

SET = """() => {
  const input = document.querySelector('.atsx-select-search__field');
  input.focus();
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(input, '上海');
  input.dispatchEvent(new Event('input', {bubbles:true}));
  input.dispatchEvent(new KeyboardEvent('keyup', {bubbles:true, key:'海'}));
  return 'set';
}"""

CHECK = """() => {
  const dd = [...document.querySelectorAll('[class*="dropdown"], [class*="option"], [class*="menu-item"]')];
  return dd.filter(e => /atsx|select|city/i.test(e.className||'')).map(e => ({
    cls: (e.className||'').toString().slice(0,60),
    vis: Math.round(e.getBoundingClientRect().height),
    txt: (e.textContent||'').trim().slice(0,80)})).slice(0,25);
}"""


async def main():
    async with MCPBrowser(user_data_dir=PROFILE, headless=False) as b:
        await b.navigate(URL)
        await b.wait_for(time=3)
        await b.click("e112")
        await b.wait_for(time=1)
        await b.call("browser_evaluate", {"function": SET})
        await b.wait_for(time=3)
        r = await b.call("browser_evaluate", {"function": CHECK})
        print(r.split("### Ran")[0][:2500])
        await b.wait_for(time=1)


asyncio.run(main())
