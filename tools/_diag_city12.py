"""验证点击北京选项能选中。"""
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
        # 重新拿快照确认选项 ref
        snap = await b.snapshot()
        import re
        m = re.search(r'option "北京" \[ref=(e\d+)\]', snap)
        ref = m.group(1) if m else "e515"
        print("北京 option ref:", ref)
        out = await b.click(ref)
        print("click tail:", out[-200:])
        await b.wait_for(time=2)
        snap2 = await b.snapshot()
        # 确认选中
        for line in snap2.splitlines():
            if "意向城市" in line or ("北京" in line and "combobox" in line) or "tag" in line.lower():
                print(line)
        await b.wait_for(time=1)


asyncio.run(main())
