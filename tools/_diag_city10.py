"""确定性实验：原生事件触发"上海"，查完整选项。"""
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
  input.dispatchEvent(new Event('change', {bubbles:true}));
}"""

CHECK = """() => {
  const items = [...document.querySelectorAll('.atsx-select-dropdown-menu-item')];
  return {total: items.length, all: items.map(i => i.textContent.trim())};
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
        print("上海 ->", r.split("### Ran")[0][:400])
        await b.wait_for(time=1)


asyncio.run(main())
