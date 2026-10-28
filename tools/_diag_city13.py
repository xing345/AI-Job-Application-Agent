"""点击北京后检查选中状态。"""
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
}"""

CHECK = """() => {
  const sel = document.querySelector('[class*="city-select"]');
  const tags = [...document.querySelectorAll('[class*="selection__item"], [class*="tag"]')]
    .map(t => t.textContent.trim()).filter(Boolean);
  return {cityText: sel ? sel.textContent.trim().slice(0,80) : null, tags: tags.slice(0,10)};
}"""


async def main():
    async with MCPBrowser(user_data_dir=PROFILE, headless=False) as b:
        await b.navigate(URL)
        await b.wait_for(time=3)
        await b.click("e112")
        await b.wait_for(time=1)
        await b.call("browser_evaluate", {"function": SET})
        await b.wait_for(time=3)
        snap = await b.snapshot()
        import re
        m = re.search(r'option "北京" \[ref=(e\d+)\]', snap)
        ref = m.group(1) if m else "e515"
        await b.click(ref)
        await b.wait_for(time=2)
        r = await b.call("browser_evaluate", {"function": CHECK})
        print(r.split("### Ran")[0][:800])
        await b.wait_for(time=1)


asyncio.run(main())
