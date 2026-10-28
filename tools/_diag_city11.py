"""触发城市下拉后，找北京/深圳选项的 ref。"""
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


async def main():
    async with MCPBrowser(user_data_dir=PROFILE, headless=False) as b:
        await b.navigate(URL)
        await b.wait_for(time=3)
        await b.click("e112")
        await b.wait_for(time=1)
        await b.call("browser_evaluate", {"function": SET})
        await b.wait_for(time=3)
        snap = await b.snapshot()
        lines = snap.splitlines()
        for i, line in enumerate(lines):
            if "北京" in line or "深圳" in line or "combobox" in line or "listbox" in line or "option" in line:
                print(line)
        await b.wait_for(time=1)


asyncio.run(main())
