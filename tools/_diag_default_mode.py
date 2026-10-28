"""默认 MCP 模式（不指定 user-data-dir），看 navigate 后是否跳 about:blank。"""
import asyncio
from src.browser_agent.mcp_client import MCPBrowser

URL = "https://jobs.bytedance.com/campus/resume/7698959353864505653/apply?spread=DWA3PQP"


async def main():
    async with MCPBrowser(headless=True) as b:
        await b.navigate(URL)
        for i in range(5):
            r = await b.call("browser_evaluate", {"function": "() => location.href"})
            url = [l for l in r.splitlines() if "http" in l or "about" in l]
            print(f"t{i}:", url[:1])
            await b.wait_for(time=1)


asyncio.run(main())
