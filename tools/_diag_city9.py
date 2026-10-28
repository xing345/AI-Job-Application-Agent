"""对照：不输入 / 输入北 / 输入上，看选项变化。"""
import asyncio
from pathlib import Path
from src.browser_agent.mcp_client import MCPBrowser

PROFILE = str(Path("data/browser_profile_mcp").resolve())
URL = "https://jobs.bytedance.com/campus/resume/7698959353864505653/apply?spread=DWA3PQP"

JS = """() => [...document.querySelectorAll('.atsx-select-dropdown-menu-item')]
          .map(i => i.textContent.trim())"""


async def main():
    async with MCPBrowser(user_data_dir=PROFILE, headless=False) as b:
        await b.navigate(URL)
        await b.wait_for(time=3)
        await b.click("e112")
        await b.wait_for(time=2)
        print("不输入:", (await b.call("browser_evaluate", {"function": JS})).split("### Ran")[0][:300])
        await b.type("e117", "北")
        await b.wait_for(time=2)
        print("输入北:", (await b.call("browser_evaluate", {"function": JS})).split("### Ran")[0][:300])
        # 清空再输入上
        await b.call("browser_evaluate", {"function": "() => {const i=document.querySelector('.atsx-select-search__field'); const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set; s.call(i,''); i.dispatchEvent(new Event('input',{bubbles:true}));}"})
        await b.wait_for(time=1)
        await b.type("e117", "上")
        await b.wait_for(time=2)
        print("输入上:", (await b.call("browser_evaluate", {"function": JS})).split("### Ran")[0][:300])
        await b.wait_for(time=1)


asyncio.run(main())
